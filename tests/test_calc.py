import unittest
from blackchpok_ide.calc import add, subtract, multiply, divide

class TestCalc(unittest.TestCase):
    def test_add(self):
        self.assertEqual(add(10, 5), 15)
    
    def test_subtract(self):
        self.assertEqual(subtract(10, 5), 5)
    
    def test_multiply(self):
        self.assertEqual(multiply(10, 5), 50)
    
    def test_divide(self):
        self.assertEqual(divide(10, 5), 2)
        self.assertEqual(divide(10, 0), 'Error: Division by zero')

if __name__ == '__main__':
    unittest.main()