import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class CreateAndAttachMasterChapterTests(unittest.TestCase):
    def test_program_page_preserves_program_context(self):
        template = (
            ROOT / "templates/lms_admin/lms_chapters.html"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "master_chapter_new', source_program_id=data.program.id",
            template,
        )

    def test_create_route_validates_tenant_and_links_transactionally(self):
        routes = (
            ROOT / "modules/lms_admin/routes.py"
        ).read_text(encoding="utf-8")
        start = routes.index("def master_chapter_new():")
        end = routes.index(
            "def master_chapter_edit(master_chapter_id):",
            start,
        )
        source = routes[start:end]
        self.assertIn(
            "WHERE id = ? AND institute_id = ? AND is_deleted = 0",
            source,
        )
        self.assertIn("INSERT INTO lms_master_chapters", source)
        self.assertIn("INSERT INTO lms_program_chapters", source)
        self.assertLess(
            source.index("INSERT INTO lms_program_chapters"),
            source.index("conn.commit()"),
        )
        self.assertIn(
            "Master chapter created and linked to",
            source,
        )

    def test_form_carries_source_program(self):
        template = (
            ROOT / "templates/lms_admin/master_chapter_form.html"
        ).read_text(encoding="utf-8")
        self.assertIn('name="source_program_id"', template)
        self.assertIn("automatically linked to", template)


if __name__ == "__main__":
    unittest.main()
