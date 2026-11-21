import unittest
from greeting import greet
class T(unittest.TestCase):
    def test_greeting(self):
        self.assertEqual(greet('World'), 'Привіт, World!')