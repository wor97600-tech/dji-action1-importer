import tempfile
import unittest
from pathlib import Path


class FormTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.ref = self.root / 'ref.mp4'; self.ref.touch()
        self.src = self.root / 'input.mp4'; self.src.touch()
        self.values = dict(mode='single', ref=str(self.ref), inp=str(self.src),
            out=str(self.root/'DJI_0900.MP4'), crf='23', max_bitrate='',
            prefix='DJI_', start_number='0900', acceleration='cpu')

    def test_bad_numbers_report_validation_errors(self):
        from ui_model import validate_form
        for key, val in (('crf','abc'),('crf','52'),('max_bitrate','0'),('max_bitrate','x')):
            with self.subTest(key=key,val=val):
                with self.assertRaises(ValueError): validate_form(dict(self.values, **{key:val}))

    def test_output_cannot_overwrite_input_or_reference(self):
        from ui_model import validate_form
        for p in (self.src,self.ref):
            with self.assertRaises(ValueError):validate_form(dict(self.values,out=str(p)))

    def test_batch_path_and_number_validation(self):
        from ui_model import validate_form
        values=dict(self.values,mode='batch',inp=str(self.root),out=str(self.root/'result'))
        self.assertEqual(validate_form(values).start_number,900)
        for changes in ({'prefix':'../DJI_'},{'start_number':'-1'},{'start_number':'10000'},
                        {'out':str(self.root)},{'inp':str(self.src)}):
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):validate_form(dict(values,**changes))

    def test_valid_input_keeps_original_encoding_values(self):
        from ui_model import validate_form
        job=validate_form(dict(self.values,max_bitrate='10000'))
        self.assertEqual((job.crf,job.max_bitrate,job.acceleration),(23,10000000,'cpu'))

if __name__=='__main__':unittest.main()
