# -*- coding: utf-8 -*-
"""
Created on Sat Jul  7 20:46:26 2018

@author: l4morak
"""

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

import resampy


import os
import pandas as pd
import random
import numpy as np
import scipy
import keras
from scipy.io import wavfile
from keras.models import Model, load_model
from keras.layers import Dense, Dropout, Activation, Flatten, Input, GlobalAveragePooling2D, GlobalMaxPooling2D, Conv2D, MaxPooling2D
import sys
from keras.engine.topology import get_source_inputs
sys.path.append('/home/hudi/anaconda2/lib/python2.7/site-packages/h5py')
sys.path.append('/home/hudi/anaconda2/lib/python2.7/site-packages/Keras-2.0.6-py2.7.egg')

from keras import backend as K
import tensorflow as tf
config = tf.ConfigProto()
config.gpu_options.allow_growth = True
sess = tf.Session(config=config)
K.set_session(sess)

np.random.seed(42)

root_dir = "E:/AudioData"

esc = pd.read_csv(root_dir + "/ESC-50-master/meta/esc50.csv")

def frame(data, window_length, hop_length):
  """Convert array into a sequence of successive possibly overlapping frames.
  An n-dimensional array of shape (num_samples, ...) is converted into an
  (n+1)-D array of shape (num_frames, window_length, ...), where each frame
  starts hop_length points after the preceding one.
  This is accomplished using stride_tricks, so the original data is not
  copied.  However, there is no zero-padding, so any incomplete frames at the
  end are not included.
  Args:
    data: np.array of dimension N >= 1.
    window_length: Number of samples in each frame.
    hop_length: Advance (in samples) between each window.
  Returns:
    (N+1)-D np.array with as many rows as there are complete frames that can be
    extracted.
  """
  num_samples = data.shape[0]
  num_frames = 1 + int(np.floor((num_samples - window_length) / hop_length))
  shape = (num_frames, window_length) + data.shape[1:]
  strides = (data.strides[0] * hop_length,) + data.strides
  return np.lib.stride_tricks.as_strided(data, shape=shape, strides=strides)


def periodic_hann(window_length):
  """Calculate a "periodic" Hann window.
  The classic Hann window is defined as a raised cosine that starts and
  ends on zero, and where every value appears twice, except the middle
  point for an odd-length window.  Matlab calls this a "symmetric" window
  and np.hanning() returns it.  However, for Fourier analysis, this
  actually represents just over one cycle of a period N-1 cosine, and
  thus is not compactly expressed on a length-N Fourier basis.  Instead,
  it's better to use a raised cosine that ends just before the final
  zero value - i.e. a complete cycle of a period-N cosine.  Matlab
  calls this a "periodic" window. This routine calculates it.
  Args:
    window_length: The number of points in the returned window.
  Returns:
    A 1D np.array containing the periodic hann window.
  """
  return 0.5 - (0.5 * np.cos(2 * np.pi / window_length *
                             np.arange(window_length)))


def stft_magnitude(signal, fft_length,
                   hop_length=None,
                   window_length=None):
  """Calculate the short-time Fourier transform magnitude.
  Args:
    signal: 1D np.array of the input time-domain signal.
    fft_length: Size of the FFT to apply.
    hop_length: Advance (in samples) between each frame passed to FFT.
    window_length: Length of each block of samples to pass to FFT.
  Returns:
    2D np.array where each row contains the magnitudes of the fft_length/2+1
    unique values of the FFT for the corresponding frame of input samples.
  """
  frames = frame(signal, window_length, hop_length)
  # Apply frame window to each frame. We use a periodic Hann (cosine of period
  # window_length) instead of the symmetric Hann of np.hanning (period
  # window_length-1).
  window = periodic_hann(window_length)
  windowed_frames = frames * window
  return np.abs(np.fft.rfft(windowed_frames, int(fft_length)))


# Mel spectrum constants and functions.
_MEL_BREAK_FREQUENCY_HERTZ = 700.0
_MEL_HIGH_FREQUENCY_Q = 1127.0


def hertz_to_mel(frequencies_hertz):
  """Convert frequencies to mel scale using HTK formula.
  Args:
    frequencies_hertz: Scalar or np.array of frequencies in hertz.
  Returns:
    Object of same size as frequencies_hertz containing corresponding values
    on the mel scale.
  """
  return _MEL_HIGH_FREQUENCY_Q * np.log(
      1.0 + (frequencies_hertz / _MEL_BREAK_FREQUENCY_HERTZ))


def spectrogram_to_mel_matrix(num_mel_bins=20,
                              num_spectrogram_bins=129,
                              audio_sample_rate=8000,
                              lower_edge_hertz=125.0,
                              upper_edge_hertz=3800.0):
  """Return a matrix that can post-multiply spectrogram rows to make mel.
  Returns a np.array matrix A that can be used to post-multiply a matrix S of
  spectrogram values (STFT magnitudes) arranged as frames x bins to generate a
  "mel spectrogram" M of frames x num_mel_bins.  M = S A.
  The classic HTK algorithm exploits the complementarity of adjacent mel bands
  to multiply each FFT bin by only one mel weight, then add it, with positive
  and negative signs, to the two adjacent mel bands to which that bin
  contributes.  Here, by expressing this operation as a matrix multiply, we go
  from num_fft multiplies per frame (plus around 2*num_fft adds) to around
  num_fft^2 multiplies and adds.  However, because these are all presumably
  accomplished in a single call to np.dot(), it's not clear which approach is
  faster in Python.  The matrix multiplication has the attraction of being more
  general and flexible, and much easier to read.
  Args:
    num_mel_bins: How many bands in the resulting mel spectrum.  This is
      the number of columns in the output matrix.
    num_spectrogram_bins: How many bins there are in the source spectrogram
      data, which is understood to be fft_size/2 + 1, i.e. the spectrogram
      only contains the nonredundant FFT bins.
    audio_sample_rate: Samples per second of the audio at the input to the
      spectrogram. We need this to figure out the actual frequencies for
      each spectrogram bin, which dictates how they are mapped into mel.
    lower_edge_hertz: Lower bound on the frequencies to be included in the mel
      spectrum.  This corresponds to the lower edge of the lowest triangular
      band.
    upper_edge_hertz: The desired top edge of the highest frequency band.
  Returns:
    An np.array with shape (num_spectrogram_bins, num_mel_bins).
  Raises:
    ValueError: if frequency edges are incorrectly ordered or out of range.
  """
  nyquist_hertz = audio_sample_rate / 2.
  if lower_edge_hertz < 0.0:
    raise ValueError("lower_edge_hertz %.1f must be >= 0" % lower_edge_hertz)
  if lower_edge_hertz >= upper_edge_hertz:
    raise ValueError("lower_edge_hertz %.1f >= upper_edge_hertz %.1f" %
                     (lower_edge_hertz, upper_edge_hertz))
  if upper_edge_hertz > nyquist_hertz:
    raise ValueError("upper_edge_hertz %.1f is greater than Nyquist %.1f" %
                     (upper_edge_hertz, nyquist_hertz))
  spectrogram_bins_hertz = np.linspace(0.0, nyquist_hertz, num_spectrogram_bins)
  spectrogram_bins_mel = hertz_to_mel(spectrogram_bins_hertz)
  # The i'th mel band (starting from i=1) has center frequency
  # band_edges_mel[i], lower edge band_edges_mel[i-1], and higher edge
  # band_edges_mel[i+1].  Thus, we need num_mel_bins + 2 values in
  # the band_edges_mel arrays.
  band_edges_mel = np.linspace(hertz_to_mel(lower_edge_hertz),
                               hertz_to_mel(upper_edge_hertz), num_mel_bins + 2)
  # Matrix to post-multiply feature arrays whose rows are num_spectrogram_bins
  # of spectrogram values.
  mel_weights_matrix = np.empty((num_spectrogram_bins, num_mel_bins))
  for i in range(num_mel_bins):
    lower_edge_mel, center_mel, upper_edge_mel = band_edges_mel[i:i + 3]
    # Calculate lower and upper slopes for every spectrogram bin.
    # Line segments are linear in the *mel* domain, not hertz.
    lower_slope = ((spectrogram_bins_mel - lower_edge_mel) /
                   (center_mel - lower_edge_mel))
    upper_slope = ((upper_edge_mel - spectrogram_bins_mel) /
                   (upper_edge_mel - center_mel))
    # .. then intersect them with each other and zero.
    mel_weights_matrix[:, i] = np.maximum(0.0, np.minimum(lower_slope,
                                                          upper_slope))
  # HTK excludes the spectrogram DC bin; make sure it always gets a zero
  # coefficient.
  mel_weights_matrix[0, :] = 0.0
  return mel_weights_matrix


def log_mel_spectrogram(data,
                        audio_sample_rate=8000,
                        log_offset=0.0,
                        window_length_secs=0.025,
                        hop_length_secs=0.010,
                        **kwargs):
  """Convert waveform to a log magnitude mel-frequency spectrogram.
  Args:
    data: 1D np.array of waveform data.
    audio_sample_rate: The sampling rate of data.
    log_offset: Add this to values when taking log to avoid -Infs.
    window_length_secs: Duration of each window to analyze.
    hop_length_secs: Advance between successive analysis windows.
    **kwargs: Additional arguments to pass to spectrogram_to_mel_matrix.
  Returns:
    2D np.array of (num_frames, num_mel_bins) consisting of log mel filterbank
    magnitudes for successive frames.
  """
  window_length_samples = int(round(audio_sample_rate * window_length_secs))
  hop_length_samples = int(round(audio_sample_rate * hop_length_secs))
  fft_length = 2 ** int(np.ceil(np.log(window_length_samples) / np.log(2.0)))
  spectrogram = stft_magnitude(
      data,
      fft_length=fft_length,
      hop_length=hop_length_samples,
      window_length=window_length_samples)
  mel_spectrogram = np.dot(spectrogram, spectrogram_to_mel_matrix(
      num_spectrogram_bins=spectrogram.shape[1],
      audio_sample_rate=audio_sample_rate, **kwargs))
  return np.log(mel_spectrogram + log_offset)

# Architectural constants.
NUM_FRAMES = 496  # Frames in input mel-spectrogram patch.
NUM_BANDS = 64  # Frequency bands in input mel-spectrogram patch.
EMBEDDING_SIZE = 128  # Size of embedding layer.

# Hyperparameters used in feature and example generation.
SAMPLE_RATE = 16000
STFT_WINDOW_LENGTH_SECONDS = 0.025
STFT_HOP_LENGTH_SECONDS = 0.010
NUM_MEL_BINS = NUM_BANDS
MEL_MIN_HZ = 125
MEL_MAX_HZ = 7500
LOG_OFFSET = 0.01  # Offset used for stabilized log of input mel-spectrogram.
EXAMPLE_WINDOW_SECONDS = 4.96  # Each example contains 96 10ms frames
EXAMPLE_HOP_SECONDS = 4.96     # with zero overlap.

# Parameters used for embedding postprocessing.
PCA_EIGEN_VECTORS_NAME = 'pca_eigen_vectors'
PCA_MEANS_NAME = 'pca_means'
QUANTIZE_MIN_VAL = -2.0
QUANTIZE_MAX_VAL = +2.0

# Hyperparameters used in training.
INIT_STDDEV = 0.01  # Standard deviation used to initialize weights.
LEARNING_RATE = 1e-4  # Learning rate for the Adam optimizer.
ADAM_EPSILON = 1e-8  # Epsilon for the Adam optimizer.

# Names of ops, tensors, and features.
INPUT_OP_NAME = 'vggish/input_features'
INPUT_TENSOR_NAME = INPUT_OP_NAME + ':0'
OUTPUT_OP_NAME = 'vggish/embedding'
OUTPUT_TENSOR_NAME = OUTPUT_OP_NAME + ':0'
AUDIO_EMBEDDING_FEATURE_NAME = 'audio_embedding'

def preprocess_sound(data, sample_rate):
  """Converts audio waveform into an array of examples for VGGish.

  Args:
    data: np.array of either one dimension (mono) or two dimensions
      (multi-channel, with the outer dimension representing channels).
      Each sample is generally expected to lie in the range [-1.0, +1.0],
      although this is not required.
    sample_rate: Sample rate of data.

  Returns:
    3-D np.array of shape [num_examples, num_frames, num_bands] which represents
    a sequence of examples, each of which contains a patch of log mel
    spectrogram, covering num_frames frames of audio and num_bands mel frequency
    bands, where the frame length is STFT_HOP_LENGTH_SECONDS.
  """
  # Convert to mono.

  if len(data.shape) > 1:
    data = np.mean(data, axis=1)
  # Resample to the rate assumed by VGGish.
  if sample_rate != SAMPLE_RATE:
    data = resampy.resample(data, sample_rate, SAMPLE_RATE)

  # Compute log mel spectrogram features.
  log_mel = scipy.misc.imresize(log_mel_spectrogram(
      data,
      audio_sample_rate=SAMPLE_RATE,
      log_offset=LOG_OFFSET,
      window_length_secs=STFT_WINDOW_LENGTH_SECONDS,
      hop_length_secs=STFT_HOP_LENGTH_SECONDS,
      num_mel_bins=NUM_MEL_BINS,
      lower_edge_hertz=MEL_MIN_HZ,
      upper_edge_hertz=MEL_MAX_HZ), (496,64)).astype(np.float64)

  # Frame features into examples.
  features_sample_rate = 1.0 / STFT_HOP_LENGTH_SECONDS
  example_window_length = int(round(
      EXAMPLE_WINDOW_SECONDS * features_sample_rate))
  example_hop_length = int(round(
      EXAMPLE_HOP_SECONDS * features_sample_rate))
  log_mel_examples = frame(
      log_mel,
      window_length=example_window_length,
      hop_length=example_hop_length)
  return log_mel_examples





# weight path
WEIGHTS_PATH = 'E:/vggish_audioset_weights_without_fc2.h5'
WEIGHTS_PATH_TOP = 'E:/vggish_audioset_weights.h5'

def VGGish(load_weights=True, weights='audioset',
           input_tensor=None, input_shape=None,
           out_dim=None, include_top=True, pooling='avg'):
    '''
    An implementation of the VGGish architecture.

    :param load_weights: if load weights
    :param weights: loads weights pre-trained on a preliminary version of YouTube-8M.
    :param input_tensor: input_layer
    :param input_shape: input data shape
    :param out_dim: output dimension
    :param include_top:whether to include the 3 fully-connected layers at the top of the network.
    :param pooling: pooling type over the non-top network, 'avg' or 'max'

    :return: A Keras model instance.
    '''

    if weights not in {'audioset', None}:
        raise ValueError('The `weights` argument should be either '
                         '`None` (random initialization) or `audioset` '
                         '(pre-training on audioset).')

    if out_dim is None:
        out_dim = EMBEDDING_SIZE

    # input shape
    if input_shape is None:
        input_shape = (NUM_FRAMES, NUM_BANDS, 1)

    if input_tensor is None:
        aud_input = Input(shape=input_shape, name='input_1')
    else:
        if not K.is_keras_tensor(input_tensor):
            aud_input = Input(tensor=input_tensor, shape=input_shape, name='input_1')
        else:
            aud_input = input_tensor



    # Block 1
    x = Conv2D(64, (3, 3), strides=(1, 1), activation='relu', padding='same', name='conv1')(aud_input)
    x = MaxPooling2D((2, 2), strides=(2, 2), padding='same', name='pool1')(x)

    # Block 2
    x = Conv2D(128, (3, 3), strides=(1, 1), activation='relu', padding='same', name='conv2')(x)
    x = MaxPooling2D((2, 2), strides=(2, 2), padding='same', name='pool2')(x)

    # Block 3
    x = Conv2D(256, (3, 3), strides=(1, 1), activation='relu', padding='same', name='conv3/conv3_1')(x)
    x = Conv2D(256, (3, 3), strides=(1, 1), activation='relu', padding='same', name='conv3/conv3_2')(x)
    x = MaxPooling2D((2, 2), strides=(2, 2), padding='same', name='pool3')(x)

    # Block 4
    x = Conv2D(512, (3, 3), strides=(1, 1), activation='relu', padding='same', name='conv4/conv4_1')(x)
    x = Conv2D(512, (3, 3), strides=(1, 1), activation='relu', padding='same', name='conv4/conv4_2')(x)
    x = MaxPooling2D((2, 2), strides=(2, 2), padding='same', name='pool4')(x)



    if include_top:
        # FC block
        x = Flatten(name='flatten_')(x)
        x = Dense(4096, activation='relu', name='vggish_fc1/fc1_1')(x)
        x = Dense(4096, activation='relu', name='vggish_fc1/fc1_2')(x)
        x = Dense(out_dim, activation='relu', name='vggish_fc2')(x)
    else:
        if pooling == 'avg':
            x = GlobalAveragePooling2D()(x)
        elif pooling == 'max':
            x = GlobalMaxPooling2D()(x)


    if input_tensor is not None:
        inputs = get_source_inputs(input_tensor)
    else:
        inputs = aud_input
    # Create model.
    model = Model(inputs, x, name='VGGish')


    # load weights
    if load_weights:
        if weights == 'audioset':
            if include_top:
                model.load_weights(WEIGHTS_PATH_TOP)
            else:
                model.load_weights(WEIGHTS_PATH)
        else:
            print("failed to load weights")

    return model


list_of_files = os.listdir(root_dir + "/audio/")
a=0
found = 0
for c in range(1000000):
    try:
        file = list_of_files[a]
    except:
        if found == 0:
            break
        else:
            found = 0
            a=0

    try:
        if file.split('_').index('time') != -1 or file.split('_').index('slice') != -1:
            del list_of_files[a]
            found+=1
    except ValueError:
        None
    except IndexError:
        if found == 0:
            break
        if a != 1:
            a=0
        else:
            break
    a+=1
del list_of_files[len(list_of_files)-1]
random.shuffle(list_of_files)


list_of_file_esc = list()
list_of_file_esc_lbl = list()

for num, a in enumerate(esc['category']):
    if a == 'door_wood_creaks':
        list_of_file_esc.append(esc['filename'][num])
        list_of_file_esc_lbl.append('door')
    if a == 'door_wood_knock':
        list_of_file_esc.append(esc['filename'][num])
        list_of_file_esc_lbl.append('kd')
    if a == 'keyboard_typing':
        list_of_file_esc.append(esc['filename'][num])
        list_of_file_esc_lbl.append('keyboard')
        

X = np.zeros((len(list_of_files)+120, 496,64))

for num, name in enumerate(list_of_files):
    samp, fr = wavfile.read(root_dir + "/audio/" + str(name))
    X[num] = preprocess_sound(fr, samp).reshape(496,64)
    
for num, name in enumerate(list_of_file_esc):
    samp, fr = wavfile.read(root_dir + "/ESC-50-master/audio/" + str(name))
    X[num+1881] = preprocess_sound(fr, samp).reshape(496,64)
    

test_list = os.listdir(root_dir + "/test/")
X_test = np.zeros((len(test_list),496,64))
for num, name in enumerate(test_list):
    samp, fr = wavfile.read(root_dir + "/test/" + str(name))
    X_test[num] = preprocess_sound(fr, samp).reshape(496,64)
    
y = np.zeros((len(list_of_files)+len(list_of_file_esc_lbl), 8))
for num, name in enumerate(list_of_files):
    if name.split('_')[0] == 'background' or name.split('_')[1] == 'background':
        lbl = 'background'
    elif name.split('_')[0] in ['bg','bags'] or name.split('_')[1] in ['bg','bags']:
        lbl = 'bags'
    elif name.split('_')[0] in ['door','d'] or name.split('_')[1] in ['door','d']:
        lbl = 'door'
    elif name.split('_')[0] in ['k', 'keyboard'] or name.split('_')[1] in ['k', 'keyboard']:
        lbl = 'keyboard'
    elif name.split('_')[0] in ['knocking', 'kd'] or name.split('_')[1] in ['knocking', 'kd']:
        lbl = 'kd'
    elif name.split('_')[0] in ['ring'] or name.split('_')[1] in ['ring']:
        lbl = 'ring'
    elif name.split('_')[0] in ['speech'] or name.split('_')[1] in ['speech']:
        lbl = 'speech'
    elif name.split('_')[0] in ['tool'] or name.split('_')[1] in ['tool']:
        lbl = 'tool'
    asdf = lbl
    score = np.zeros((8))
    if asdf == 'background':
        score[0] = 1
    elif asdf in ['bg','bags']:
        score[1] = 1
    elif asdf in ['door','d']:
        score[2] = 1
    elif asdf in ['k', 'keyboard']:
        score[3] = 1
    elif asdf in ['knocking', 'kd']:
        score[4] = 1
    elif asdf in ['ring']:
        score[5] = 1
    elif asdf in ['speech']:
        score[6] = 1
    elif asdf in ['tool']:
        score[7] = 1
    y[num] = score
    
for a in range(120):
    score = np.zeros((8))
    asdf = list_of_file_esc_lbl[a]
    if asdf == 'background':
        score[0] = 1
    elif asdf in ['bg','bags']:
        score[1] = 1
    elif asdf in ['door','d']:
        score[2] = 1
    elif asdf in ['k', 'keyboard']:
        score[3] = 1
    elif asdf in ['knocking', 'kd']:
        score[4] = 1
    elif asdf in ['ring']:
        score[5] = 1
    elif asdf in ['speech']:
        score[6] = 1
    elif asdf in ['tool']:
        score[7] = 1
    y[1881+a] = score
    

y_test = np.zeros((473, 8))
for num, name in enumerate(test_list):
    if name.split('_')[0] == 'background':
        lbl = 'background'
    elif name.split('_')[0] in ['bg','bags']:
        lbl = 'bags'
    elif name.split('_')[0] in ['door','d']:
        lbl = 'door'
    elif name.split('_')[0] in ['k', 'keyboard']:
        lbl = 'keyboard'
    elif name.split('_')[0] in ['knocking', 'kd']:
        lbl = 'kd'
    elif name.split('_')[0] in ['ring']:
        lbl = 'ring'
    elif name.split('_')[0] in ['speech']:
        lbl = 'speech'
    elif name.split('_')[0] in ['tool']:
        lbl = 'tool'
    elif name.split('_')[0] in ['unknown']:
        break
    asdf = lbl
    score = np.zeros((8))
    if asdf == 'background':
        score[0] = 1
    elif asdf in ['bg','bags']:
        score[1] = 1
    elif asdf in ['door','d']:
        score[2] = 1
    elif asdf in ['k', 'keyboard']:
        score[3] = 1
    elif asdf in ['knocking', 'kd']:
        score[4] = 1
    elif asdf in ['ring']:
        score[5] = 1
    elif asdf in ['speech']:
        score[6] = 1
    elif asdf in ['tool']:
        score[7] = 1
    y_test[num] = score

mod_vgg = VGGish(include_top=False)
x_d = mod_vgg.predict(X.reshape(-1,496,64,1), verbose=1)
data = mod_vgg.predict(X_test.reshape(-1,496,64,1), verbose=1)

models = list()

def model_end():
    inp = Input((512,))
    x = Dense(800)(inp)
    x = Dropout(0.2)(x)
    x = Dense(800)(x) #105 - 0.9429 0.1744s
    x = Dropout(0.4)(x)
    x = Activation('relu')(x)
    x = Dense(8)(x)
    x = Activation('softmax')(x)
    model = Model(inputs = inp, outputs=x)
    adam = keras.optimizers.Adam(lr=0.0008, beta_1=0.9, beta_2=0.999, epsilon=None, decay=0.00, amsgrad=False)
    model.compile(loss='categorical_crossentropy', optimizer=adam, metrics=['accuracy'])
    model_checkpoint = keras.callbacks.ModelCheckpoint(root_dir + "/model.hdf5", monitor='val_acc', verbose=0, save_best_only=True)
    model.fit(x_d, y, verbose=0, epochs=10, batch_size=40, validation_split=0.1, callbacks=[model_checkpoint])
    return model

preds = np.zeros((610,8))
for a in range(5):
    model_end()
    models.append(load_model(root_dir + "/model.hdf5"))
    preds += models[a].predict(data)
    
preds /= 5

f = open('E:/AudioData/reward_baseline.txt', 'w')
for num, song in enumerate(test_list):
    l = preds[num].argmax()
    if l == 0:
        lbl = 'background'
    elif l == 1:
        lbl = 'bags'
    elif l == 2:
        lbl = 'door'
    elif l==3:
        lbl = 'keyboard'
    elif l==4:
        lbl = 'kd'
    elif l==5:
        lbl = 'ring'
    elif l==6:
        lbl = 'speech'
    elif l==7:
        lbl = 'tool'

    f.write(str(song) + '   ' + str(preds[num].max()) + '   ' + str(lbl) + '\n')
f.close()