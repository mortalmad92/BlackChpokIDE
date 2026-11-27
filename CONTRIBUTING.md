# Як допомогти в розвитку BlackChpok IDE

Ми раді будь-яким покращенням, виправленням помилок та новим інструментам!

## Пошаговий процес (Pull Request)
1. Натисніть **Fork** у верхньому куті сторінки репозиторію.
2. Створіть гілку для своєї фічі (`git checkout -b feat/my-feature`).
3. Перед відправкою перевірте стиль і тести:
```bash
python tests/check_style.py
python main.py --selftest
python -m unittest discover -s tests
```
4. Відкрийте **Pull Request** у гілку `main`.
