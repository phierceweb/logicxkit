"""iZotope's zlib-over-JSON state: the header, the typed document, its parameters by module."""

import unittest

from logicxkit.au.services.izotope import IzotopeError, dsp_values, pack_izotope, parse_izotope


def doc(**modules) -> dict:
    return {"DSP State": {"Type": "Dictionary", "Value": {"DSP Elements": {"Type": "Dictionary", "Value": {
        name: {"Type": "Dictionary", "Value": {k: {"Type": "Float" if isinstance(v, float) else "Bool" if isinstance(v, bool) else "UInt", "Value": v}
                                               for k, v in params.items()}}
        for name, params in modules.items()}}}}, "Major Version": {"Type": "UInt", "Value": 5}}


class IzotopeStateTest(unittest.TestCase):
    def test_a_packed_document_reads_back_by_module_and_parameter(self):
        d = doc(**{"Dynamics 0": {"Band 0 Comp Threshold": -18.5, "Band 0 Comp Ratio": 4.0, "Bypass": False},
                   "Dynamic EQ": {"Band 1 Frequency": 250.0, "Band 1 Shape": 0}})
        blob = pack_izotope(d)
        self.assertEqual(blob[:4].hex(), "83fb8000")
        values = dsp_values(parse_izotope(blob))
        self.assertEqual(values["Dynamics 0/Band 0 Comp Threshold"], -18.5)
        self.assertEqual((values["Dynamics 0/Bypass"], values["Dynamic EQ/Band 1 Shape"]), (False, 0))
        self.assertEqual(len(values), 5)

    def test_other_blobs_are_refused(self):
        with self.assertRaises(IzotopeError):
            parse_izotope(b"\x00" * 40)
        with self.assertRaises(IzotopeError):
            parse_izotope(bytes.fromhex("83fb8000" + "01000000" + "05000000" + "10000000") + b"nope!")


if __name__ == "__main__":
    unittest.main()
