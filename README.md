# Classifier of Acoustic Events
Решение задачи "Классификатор акустических событий". (файл main.py)

Лучшая точность на известных объектах test выборки - 95 % (Accuracy Score);

Модель использует сверточные слои модели VGGish. 
(https://github.com/tensorflow/models/tree/master/research/audioset - ссылка на оригинальный источник)  
Результаты VGGish передаются сети с тремя слоями. (800 нейронов, батч-нормализация, 800 нейронов, батч-нормализация, ReLU, 8 нейронов, Softmax)

Для расчета конечного результата используются 10 одинаковых сетей, берется среднее арифметическое их предсказаний. Это сделано из-за того, что конечный результат после обучения модели может сильно отличаться на 5-8 % в худшую сторону.

Для запуска разместите внутри одной папки две папки: audio/, test/.
В файле main.py значение переменной root_dir замените на путь к этой папке. 

P.S. Рекомендуется использовать GPU.  
P.P.S Результаты немного улучшились. Заметил опечатку в коде.  
P.P.P.S Результаты заметно улучшились. Перенес VGGish внутрь модели и добавил батч-нормализацию вместо дропаута
