# Classifier of Acoustic Events
Решение задачи "Классификатор акустических событий". 

Средняя точность на известных объектах test выборки - 82-83 % (Accuracy Score); 97.5 % (ROC AUC Score); 86 % (Mean Average Precision).  
Для обучения модели также использовался датасет ESC-50. (https://github.com/karoldvl/ESC-50)

Модель использует предобученные сверточные слои модели VGGish. 
(https://github.com/tensorflow/models/tree/master/research/audioset - ссылка на оригинальный источник)
(https://github.com/DTaoo/VGGish - VGGish на Keras)  
Результаты VGGish передаются полносвязной сети с тремя слоями. (800 нейронов, 800 нейронов, 8 нейронов)

Для расчета конечного результата используются 5 сетей, берется среднее арифметическое их предсказаний. Это сделано из-за того, что конечный результат после обучения модели может сильно отличаться на 2-4 % в худшую сторону.