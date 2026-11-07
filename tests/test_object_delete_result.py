import unittest

from cavi_blender_mcp.contracts import ObjectEditResult


class ObjectDeleteResultTests(unittest.TestCase):
    def test_deleted_names_require_a_consistent_count_and_root(self):
        value={'name':'Draft','deleted':['Draft'],'count':1}
        try:
            ObjectEditResult.model_validate(value)
        except ValueError as exc:
            self.fail(f'Object deletion receipts are unavailable: {exc}')
        for change in ({'count':2},{'count':True},{'deleted':[]},
                       {'deleted':['Other']},{'deleted':['Draft','Draft'],'count':2}):
            with self.subTest(change=change),self.assertRaises(ValueError):
                ObjectEditResult.model_validate({**value,**change})
