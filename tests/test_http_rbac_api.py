import os
import tempfile
import unittest

from auth_service import AuthService
from http_rbac_api import RbacHttpApi
from rbac_service import RbacService
from rbac_store import RbacStore


class TestHttpRbacApi(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = RbacStore(os.path.join(self.tmp.name, "rbac.db"))
        self.store.ensure_schema()
        self.store.seed_defaults()
        self.auth = AuthService(self.store)
        self.auth.ensure_seed_director("ChangeMe123!")
        self.api = RbacHttpApi(self.store, self.auth, RbacService(self.store))

    def tearDown(self):
        self.tmp.cleanup()

    def _auth_header(self, token: str) -> str:
        return f"Bearer {token}"

    def test_login_ok_and_bad(self):
        status, body = self.api.login({"username": "director", "password": "ChangeMe123!"})
        self.assertEqual(status, 200)
        self.assertIn("token", body)
        status2, _ = self.api.login({"username": "director", "password": "nope"})
        self.assertEqual(status2, 401)

    def test_users_require_cap(self):
        status, _ = self.api.list_users(None)
        self.assertEqual(status, 401)
        login = self.api.login({"username": "director", "password": "ChangeMe123!"})[1]
        status, body = self.api.list_users(self._auth_header(login["token"]))
        self.assertEqual(status, 200)
        self.assertTrue(any(u["username"] == "director" for u in body["users"]))

    def test_assign_case_member(self):
        login = self.api.login({"username": "director", "password": "ChangeMe123!"})[1]
        hdr = self._auth_header(login["token"])
        created_users = []
        for name in ("p1", "l1", "a1"):
            st, created = self.api.create_user(
                hdr,
                {
                    "username": name,
                    "password": "pass12345",
                    "display_name": name,
                    "roles": [],
                    "must_change_password": False,
                },
            )
            self.assertEqual(st, 201)
            created_users.append(created["user"]["id"])
        st, case_body = self.api.create_case(
            hdr,
            {
                "case_type": "civil",
                "title": "测试案",
                "partner_user_id": created_users[0],
                "lead_lawyer_user_id": created_users[1],
                "assistant_user_id": created_users[2],
                "contract_file_ids": ["contract-1"],
                "evidence_file_ids": ["ev-1", "ev-2"],
            },
        )
        self.assertEqual(st, 201)
        self.assertEqual(len(case_body.get("members") or []), 3)
        self.assertEqual(case_body["case"]["status"], "assigned")
        self.assertEqual(case_body["case"]["status_label"], "已分案")
        self.assertEqual(case_body["case"]["case_type"], "civil")
        self.assertEqual(case_body["case"]["case_type_label"], "民事")
        self.assertTrue(case_body["case"]["case_no"].startswith(f"{__import__('datetime').datetime.now().year}民"))
        self.assertEqual(case_body["case"]["contract_file_ids"], ["contract-1"])
        self.assertEqual(case_body["case"]["evidence_file_ids"], ["ev-1", "ev-2"])
        roles = {m["role_code"] for m in case_body["members"]}
        self.assertEqual(roles, {"partner", "lead_lawyer", "assistant"})

        st_bad, bad = self.api.create_case(
            hdr,
            {
                "case_type": "civil",
                "title": "超限案",
                "partner_user_id": created_users[0],
                "lead_lawyer_user_id": created_users[1],
                "assistant_user_id": created_users[2],
                "contract_file_ids": ["c1", "c2"],
            },
        )
        self.assertEqual(st_bad, 400)
        self.assertIn("委托合同", bad.get("error", ""))

        st_bad2, bad2 = self.api.create_case(
            hdr,
            {
                "case_type": "civil",
                "title": "超限证据",
                "partner_user_id": created_users[0],
                "lead_lawyer_user_id": created_users[1],
                "assistant_user_id": created_users[2],
                "evidence_file_ids": [f"e{i}" for i in range(11)],
            },
        )
        self.assertEqual(st_bad2, 400)
        self.assertIn("证据材料", bad2.get("error", ""))

        st2, case2 = self.api.create_case(
            hdr,
            {
                "case_type": "civil",
                "title": "测试案2",
                "partner_user_id": created_users[0],
                "lead_lawyer_user_id": created_users[1],
                "assistant_user_id": created_users[2],
            },
        )
        self.assertEqual(st2, 201)
        self.assertNotEqual(case_body["case"]["case_no"], case2["case"]["case_no"])

        st3, case3 = self.api.create_case(
            hdr,
            {
                "case_type": "civil",
                "title": "无助理案",
                "partner_user_id": created_users[0],
                "lead_lawyer_user_id": created_users[1],
            },
        )
        self.assertEqual(st3, 201)
        self.assertEqual(
            {m["role_code"] for m in case3.get("members") or []},
            {"partner", "lead_lawyer"},
        )

        preview = self.api.preview_case_no(hdr, "criminal")
        self.assertEqual(preview[0], 200)
        self.assertIn("刑", preview[1]["case_no"])

    def test_case_clients_and_delete(self):
        login = self.api.login({"username": "director", "password": "ChangeMe123!"})[1]
        hdr = self._auth_header(login["token"])
        created_users = []
        for name in ("pc1", "lc1", "ac1"):
            st, created = self.api.create_user(
                hdr,
                {
                    "username": name,
                    "password": "pass12345",
                    "display_name": name,
                    "roles": [],
                    "must_change_password": False,
                },
            )
            self.assertEqual(st, 201)
            created_users.append(created["user"]["id"])
        st, client = self.api.create_client(
            hdr,
            {"name": "王五", "client_type": "person", "id_number": "110101199002021111"},
        )
        self.assertEqual(st, 201)
        st, case_body = self.api.create_case(
            hdr,
            {
                "case_type": "criminal",
                "title": "关联客户案",
                "partner_user_id": created_users[0],
                "lead_lawyer_user_id": created_users[1],
                "assistant_user_id": created_users[2],
                "client_ids": [client["client"]["id"]],
            },
        )
        self.assertEqual(st, 201)
        self.assertEqual(len(case_body["clients"]), 1)
        st, detail = self.api.get_case(hdr, case_body["case"]["id"])
        self.assertEqual(st, 200)
        self.assertEqual(detail["clients"][0]["name"], "王五")
        st, updated = self.api.update_case(
            hdr,
            case_body["case"]["id"],
            {"title": "关联客户案-改", "client_ids": []},
        )
        self.assertEqual(st, 200)
        self.assertEqual(updated["case"]["title"], "关联客户案-改")
        self.assertEqual(updated["clients"], [])
        st, deleted = self.api.delete_case(hdr, case_body["case"]["id"])
        self.assertEqual(st, 200)
        st, missing = self.api.get_case(hdr, case_body["case"]["id"])
        self.assertEqual(st, 404)


    def test_create_user_with_account_status(self):
        login = self.api.login({"username": "director", "password": "ChangeMe123!"})[1]
        hdr = self._auth_header(login["token"])
        st, created = self.api.create_user(
            hdr,
            {
                "username": "locked_user",
                "password": "pass12345",
                "display_name": "锁定员工",
                "roles": ["admin_officer"],
                "account_status": "locked",
                "must_change_password": False,
            },
        )
        self.assertEqual(st, 201)
        self.assertEqual(created["user"]["account_status"], "locked")
        self.assertEqual(created["user"]["account_status_label"], "锁定")
        self.assertFalse(created["user"]["is_active"])
        st2, _ = self.api.login({"username": "locked_user", "password": "pass12345"})
        self.assertEqual(st2, 401)

        st3, active = self.api.create_user(
            hdr,
            {
                "username": "active_user",
                "password": "pass12345",
                "display_name": "在职员工",
                "roles": [],
                "account_status": "active",
                "must_change_password": False,
            },
        )
        self.assertEqual(st3, 201)
        self.assertEqual(active["user"]["account_status"], "active")
        st4, body = self.api.update_user(
            hdr,
            active["user"]["id"],
            {"account_status": "resigned", "display_name": "已离职"},
        )
        self.assertEqual(st4, 200)
        self.assertEqual(body["user"]["account_status"], "resigned")
        self.assertEqual(body["user"]["display_name"], "已离职")
        st5, _ = self.api.login({"username": "active_user", "password": "pass12345"})
        self.assertEqual(st5, 401)

    def test_clients_crud(self):
        login = self.api.login({"username": "director", "password": "ChangeMe123!"})[1]
        hdr = self._auth_header(login["token"])
        st, created = self.api.create_client(
            hdr,
            {
                "name": "张三",
                "client_type": "person",
                "id_number": "110101199001011237",
            },
        )
        self.assertEqual(st, 201)
        self.assertEqual(created["client"]["client_type_label"], "个人")
        st2, listed = self.api.list_clients(hdr)
        self.assertEqual(st2, 200)
        self.assertTrue(any(c["id_number"] == "110101199001011237" for c in listed["clients"]))
        st3, updated = self.api.update_client(
            hdr,
            created["client"]["id"],
            {"name": "张三丰", "client_type": "person", "id_number": "110101199001011237"},
        )
        self.assertEqual(st3, 200)
        self.assertEqual(updated["client"]["name"], "张三丰")
        st4, dup = self.api.create_client(
            hdr,
            {
                "name": "李四",
                "client_type": "person",
                "id_number": "110101199001011237",
            },
        )
        self.assertEqual(st4, 400)
        st_bad, bad = self.api.create_client(
            hdr,
            {
                "name": "短号",
                "client_type": "person",
                "id_number": "12345",
            },
        )
        self.assertEqual(st_bad, 400)
        self.assertIn("18", bad.get("error", ""))
        st5, company = self.api.create_client(
            hdr,
            {
                "name": "某某科技有限公司",
                "client_type": "enterprise",
                "id_number": "91110000MA01234567",
            },
        )
        self.assertEqual(st5, 201)
        self.assertEqual(company["client"]["client_type_label"], "企业")
        st6, deleted = self.api.delete_client(hdr, created["client"]["id"])
        self.assertEqual(st6, 200)


if __name__ == "__main__":
    unittest.main()
