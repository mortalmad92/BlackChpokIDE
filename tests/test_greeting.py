import unittest
from greeting import greeting
class TestGreeting(unittest.TestCase):
    def test_hello(self):
        self.assertEqual(greeting('World'), 'Hello, World!')