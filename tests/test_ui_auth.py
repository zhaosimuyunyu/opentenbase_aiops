import os
import importlib.util
import sys
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

from frontend.auth import require_ui_auth, ui_password_matches

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "frontend"))


class StopScript(Exception):
    pass


class RerunScript(Exception):
    pass


class FakeStreamlit:
    def __init__(self, candidate="", submitted=True):
        self.session_state = {}
        self.candidate = candidate
        self.submitted = submitted
        self.errors = []

    def title(self, _value):
        pass

    def caption(self, _value):
        pass

    def form(self, _key, clear_on_submit=False):
        return nullcontext()

    def text_input(self, _label, type=None):
        return self.candidate

    def form_submit_button(self, _label):
        return self.submitted

    def error(self, message):
        self.errors.append(message)

    def rerun(self):
        raise RerunScript

    def stop(self):
        raise StopScript


class UiAuthenticationTests(unittest.TestCase):
    def test_password_comparison_fails_closed_and_uses_expected_value(self):
        self.assertTrue(ui_password_matches("correct", "correct"))
        self.assertFalse(ui_password_matches("wrong", "correct"))
        self.assertFalse(ui_password_matches("", ""))

    def test_successful_login_sets_only_server_session_flag(self):
        ui = FakeStreamlit(candidate="correct")
        with patch.dict(os.environ, {"AIOPS_UI_PASSWORD": "correct"}):
            with self.assertRaises(RerunScript):
                require_ui_auth(ui)

        self.assertEqual(ui.session_state, {"_aiops_ui_authenticated": True})

    def test_invalid_login_stops_rendering_and_reports_error(self):
        ui = FakeStreamlit(candidate="wrong")
        with patch.dict(os.environ, {"AIOPS_UI_PASSWORD": "correct"}):
            with self.assertRaises(StopScript):
                require_ui_auth(ui)

        self.assertEqual(ui.errors, ["访问密码不正确"])
        self.assertNotIn("_aiops_ui_authenticated", ui.session_state)

    def test_empty_password_keeps_local_development_flow(self):
        ui = FakeStreamlit()
        with patch.dict(os.environ, {}, clear=True):
            require_ui_auth(ui)

        self.assertEqual(ui.session_state, {})

    @unittest.skipUnless(importlib.util.find_spec("streamlit"), "Streamlit is not installed")
    def test_streamlit_app_hides_content_until_login_succeeds(self):
        from streamlit.testing.v1 import AppTest

        script = (
            "import streamlit as st\n"
            "from auth import require_ui_auth\n"
            "require_ui_auth(st)\n"
            "st.write('protected-content')\n"
        )
        with patch.dict(os.environ, {"AIOPS_UI_PASSWORD": "correct"}):
            app = AppTest.from_string(script).run()
            self.assertEqual(len(app.text_input), 1)
            self.assertFalse(any("protected-content" in item.value for item in app.markdown))
            app.text_input[0].set_value("correct")
            app.button[0].click().run()

        self.assertTrue(any("protected-content" in item.value for item in app.markdown))


if __name__ == "__main__":
    unittest.main()
