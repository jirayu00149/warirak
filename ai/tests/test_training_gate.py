import unittest
from warirak_ai.train_balanced import promotion_gate

class TrainingGateTests(unittest.TestCase):
    def setUp(self):self.base={'map50_95':.38,'classes':{'plastic_bottle':.37,'bottle_cap':.39}}
    def test_macro_gain_and_both_classes_are_required(self):
        self.assertTrue(promotion_gate(self.base,{'map50_95':.39,'classes':{'plastic_bottle':.40,'bottle_cap':.38}}))
        self.assertFalse(promotion_gate(self.base,{'map50_95':.39,'classes':{'plastic_bottle':.43,'bottle_cap':.35}}))
        self.assertFalse(promotion_gate(self.base,{'map50_95':.381,'classes':{'plastic_bottle':.38,'bottle_cap':.39}}))
        self.assertFalse(promotion_gate(self.base,{'map50_95':.40,'classes':{'plastic_bottle':.45}}))
    def test_no_test_score_can_change_selection(self):
        candidate={'map50_95':.37,'classes':{'plastic_bottle':.38,'bottle_cap':.39},'test_map50_95':.99}
        self.assertFalse(promotion_gate(self.base,candidate))

if __name__=='__main__':unittest.main()
