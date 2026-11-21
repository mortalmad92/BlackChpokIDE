import unittest
from main import app

class TestMain(unittest.TestCase):
    def test_app(self):
        self.assertEqual(app, 'BlackChpok IDE')