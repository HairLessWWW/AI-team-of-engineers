from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

from ai_engineering_platform.project_materials import (
    ProjectMaterials,
    extract_docx_text,
    extract_file_text,
    extract_pptx_text,
    extract_xlsx_text,
    extract_urls,
)


class ProjectMaterialsTest(unittest.TestCase):
    def test_extract_urls(self) -> None:
        urls = extract_urls("Смотри https://example.com/a?b=1 и http://test.local/doc.")

        self.assertEqual(urls, ["https://example.com/a?b=1", "http://test.local/doc"])

    def test_extract_docx_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.docx"
            with ZipFile(path, "w") as archive:
                archive.writestr(
                    "word/document.xml",
                    """
                    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
                        <w:body><w:p><w:r><w:t>Текст ТЗ</w:t></w:r></w:p></w:body>
                    </w:document>
                    """,
                )

            text = extract_docx_text(path)

        self.assertIn("Текст ТЗ", text)

    def test_extract_pptx_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "deck.pptx"
            with ZipFile(path, "w") as archive:
                archive.writestr(
                    "ppt/slides/slide1.xml",
                    """
                    <p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
                           xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
                        <p:cSld><p:spTree><p:sp><p:txBody><a:p><a:r><a:t>План сборки</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld>
                    </p:sld>
                    """,
                )

            text = extract_pptx_text(path)

        self.assertIn("Слайд 1", text)
        self.assertIn("План сборки", text)

    def test_extract_xlsx_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bom.xlsx"
            with ZipFile(path, "w") as archive:
                archive.writestr(
                    "xl/sharedStrings.xml",
                    """
                    <sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
                        <si><t>Part</t></si>
                        <si><t>Qty</t></si>
                        <si><t>Motor</t></si>
                    </sst>
                    """,
                )
                archive.writestr(
                    "xl/worksheets/sheet1.xml",
                    """
                    <worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
                      <sheetData>
                        <row r="1"><c t="s"><v>0</v></c><c t="s"><v>1</v></c></row>
                        <row r="2"><c t="s"><v>2</v></c><c><v>4</v></c></row>
                      </sheetData>
                    </worksheet>
                    """,
                )

            text = extract_xlsx_text(path)
            generic_text = extract_file_text(path, "bom.xlsx")

        self.assertIn("Лист 1", text)
        self.assertIn("Part Qty", text)
        self.assertIn("Motor 4", text)
        self.assertIn("Motor", generic_text)

    def test_store_material(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ProjectMaterials(Path(tmp) / "materials.db", Path(tmp) / "files")
            material_id = store.add_material(123, "file", "tz.docx", "Текст материала")
            recent = store.get_recent_materials(123, 5)

        self.assertEqual(material_id, 1)
        self.assertEqual(len(recent), 1)
        self.assertEqual(recent[0].title, "tz.docx")


    def test_assign_material_to_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ProjectMaterials(Path(tmp) / "materials.db", Path(tmp) / "files")
            material_id = store.add_material(123, "file", "bom.xlsx", "Motor 4")
            store.assign_to_project(material_id, 77)
            project_materials = store.get_project_materials(77, 5)

        self.assertEqual(len(project_materials), 1)
        self.assertEqual(project_materials[0].project_id, 77)
        self.assertEqual(project_materials[0].title, "bom.xlsx")


if __name__ == "__main__":
    unittest.main()
