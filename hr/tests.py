from unittest.mock import patch
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User, Group
from jobs.models import Job, Application, Requirement, Department
from hr.models import Interview
from hr.views import invalidate_hr_cache

class CandidateManagementTests(TestCase):
    def setUp(self):
        invalidate_hr_cache()
        self.client = Client()
        self.staff_user = User.objects.create_user(
            username="admin_hr",
            password="testpassword123",
            is_staff=True
        )
        self.hr_group, _ = Group.objects.get_or_create(name="HR")
        self.staff_user.groups.add(self.hr_group)
        self.client.login(username="admin_hr", password="testpassword123")

        # Create two departments with jobs
        self.sales_dept = "Sales"
        self.hr_dept = "Human Resources"

        self.job_sales_staff = Job.objects.create(
            title="Sales Staff",
            department=self.sales_dept,
            job_type="FULL-TIME",
            status="Active"
        )
        self.job_sales_mgr = Job.objects.create(
            title="Sales Manager",
            department=self.sales_dept,
            job_type="FULL-TIME",
            status="Active"
        )
        self.job_hr_spec = Job.objects.create(
            title="HR Specialist",
            department=self.hr_dept,
            job_type="FULL-TIME",
            status="Active"
        )

        # Create 10 applicants for job_sales_staff (scores 99 down to 90)
        self.sales_apps = []
        for i in range(10):
            app = Application.objects.create(
                job=self.job_sales_staff,
                first_name=f"Applicant{i+1}",
                last_name="Test",
                email=f"app{i+1}@test.com",
                phone="1234567890",
                ai_score=99 - i,
                status="Screening" if i % 2 == 0 else "Interview",
            )
            self.sales_apps.append(app)

    def test_candidates_page_loads_and_shows_structure(self):
        url = reverse("candidates")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        # Check KPI summary
        self.assertEqual(response.context["total_candidates"], 10)
        self.assertIn("department_sections", response.context)

        # Check Sales department is present
        sales_section = next(
            (d for d in response.context["department_sections"] if d["name"] == self.sales_dept),
            None
        )
        self.assertIsNotNone(sales_section)
        self.assertEqual(sales_section["total_applicants"], 10)

        # Find sales staff job in the section
        sales_staff_job = next(
            (j for j in sales_section["jobs"] if j.id == self.job_sales_staff.id),
            None
        )
        self.assertIsNotNone(sales_staff_job)

        # Top 3 candidates check
        self.assertEqual(len(sales_staff_job.top_candidates), 3)
        self.assertEqual(sales_staff_job.top_candidates[0].ai_score, 99)
        self.assertEqual(sales_staff_job.top_candidates[0].top_rank, 1)
        self.assertEqual(sales_staff_job.top_candidates[1].top_rank, 2)
        self.assertEqual(sales_staff_job.top_candidates[2].top_rank, 3)

        # Table data check (Page 1 has ranks 4 to 8, 5 candidates)
        table_data = sales_staff_job.table_data
        self.assertFalse(table_data["is_search"])
        self.assertEqual(len(table_data["candidates"]), 5)
        self.assertEqual(table_data["candidates"][0].table_rank, 4)
        self.assertEqual(table_data["candidates"][4].table_rank, 8)
        self.assertEqual(table_data["total_pages"], 2)

    def test_department_filter_dropdown(self):
        url = f"{reverse('candidates')}?department=Sales"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        dept_names = [d["name"] for d in response.context["department_sections"]]
        self.assertIn("Sales", dept_names)
        self.assertNotIn("Human Resources", dept_names)

    def test_job_table_pagination_htmx(self):
        # Fetch page 2 for sales staff table
        url = reverse("candidate_job_table", args=[self.job_sales_staff.id])
        response = self.client.get(f"{url}?page=2")
        self.assertEqual(response.status_code, 200)

        table_data = response.context["table_data"]
        # Total was 10. Top 3 are in cards. Remaining is 7.
        # Page 1 had 5 (ranks 4-8). Page 2 has 2 (ranks 9-10).
        self.assertEqual(len(table_data["candidates"]), 2)
        self.assertEqual(table_data["candidates"][0].table_rank, 9)
        self.assertEqual(table_data["candidates"][1].table_rank, 10)
        self.assertContains(response, "#9")
        self.assertContains(response, "#10")

    def test_job_table_search_htmx(self):
        # Search by specific first name
        target_app = self.sales_apps[5] # Applicant6
        url = reverse("candidate_job_table", args=[self.job_sales_staff.id])
        response = self.client.get(f"{url}?search={target_app.first_name}")
        self.assertEqual(response.status_code, 200)

        table_data = response.context["table_data"]
        self.assertTrue(table_data["is_search"])
        self.assertEqual(table_data["total_count"], 1)
        self.assertEqual(table_data["candidates"][0].id, target_app.id)
        self.assertContains(response, target_app.first_name)
        self.assertContains(response, target_app.application_id)

    def test_candidate_department_redirect(self):
        url = reverse("candidate_department", args=["Sales"])
        response = self.client.get(url)
        # Should redirect to /admin/candidates/?department=Sales
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("candidates"), response.url)
        self.assertIn("department=Sales", response.url)

    def test_job_filter_param(self):
        url = f"{reverse('candidates')}?job={self.job_sales_staff.id}"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        jobs_in_view = [j for d in response.context["department_sections"] for j in d["jobs"]]
        self.assertEqual(len(jobs_in_view), 1)
        self.assertEqual(jobs_in_view[0].id, self.job_sales_staff.id)

        # Filtering by a job with 0 applicants should return no jobs
        url_empty = f"{reverse('candidates')}?job={self.job_sales_mgr.id}"
        response_empty = self.client.get(url_empty)
        self.assertEqual(response_empty.status_code, 200)
        self.assertEqual(len(response_empty.context["department_sections"]), 0)

    def test_job_with_three_or_fewer_candidates(self):
        # Create 2 applicants for Sales Manager
        for i in range(2):
            Application.objects.create(
                job=self.job_sales_mgr,
                first_name=f"MgrApp{i+1}",
                last_name="Test",
                email=f"mgrapp{i+1}@test.com",
                phone="1234567890",
                ai_score=85 - i,
            )

        url = reverse("candidates")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        sales_section = next(d for d in response.context["department_sections"] if d["name"] == self.sales_dept)
        mgr_job = next(j for j in sales_section["jobs"] if j.id == self.job_sales_mgr.id)

        # 2 cards, table has 0 additional candidates
        self.assertEqual(len(mgr_job.top_candidates), 2)
        self.assertEqual(len(mgr_job.table_data["candidates"]), 0)

    def test_empty_search_returns_no_results(self):
        url = reverse("candidate_job_table", args=[self.job_sales_staff.id])
        response = self.client.get(f"{url}?search=NonExistentPersonXYZ")
        self.assertEqual(response.status_code, 200)
        table_data = response.context["table_data"]
        self.assertTrue(table_data["is_search"])
        self.assertEqual(len(table_data["candidates"]), 0)
        self.assertContains(response, "No candidates found matching")

    def test_high_volume_candidates_scalability(self):
        # Bulk create 200 applicants
        apps = [
            Application(
                application_id=f"BLK{i:05d}",
                job=self.job_sales_staff,
                first_name=f"BulkFirst{i}",
                last_name=f"BulkLast{i}",
                email=f"bulk{i}@test.com",
                phone="5551234567",
                ai_score=50 + (i % 40),
                status="Pending"
            )
            for i in range(200)
        ]
        Application.objects.bulk_create(apps)

        # Query candidates page and measure performance
        url = f"{reverse('candidates')}?job={self.job_sales_staff.id}"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        # Check total count is 210
        total_for_job = Application.objects.filter(job=self.job_sales_staff).count()
        self.assertEqual(total_for_job, 210)

        # Check table pagination for page 10
        url = reverse("candidate_job_table", args=[self.job_sales_staff.id])
        response = self.client.get(f"{url}?page=10")
        self.assertEqual(response.status_code, 200)
        table_data = response.context["table_data"]
        # Page 10 offset is 3 + (10 - 1) * 5 = 48. Ranks: 49 to 53.
        self.assertEqual(table_data["candidates"][0].table_rank, 49)
        self.assertEqual(table_data["candidates"][-1].table_rank, 53)

    def test_compressed_card_structure(self):
        url = reverse("candidates")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "tc-card-body")
        self.assertContains(response, "tc-left-col")
        self.assertContains(response, "tc-right-col")
        self.assertContains(response, "btn-tc-review")

    def test_pagination_always_shown_even_with_zero_candidates(self):
        # Empty search results
        url = reverse("candidate_job_table", args=[self.job_sales_staff.id])
        response = self.client.get(f"{url}?search=NoOneMatchesThisQuery")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "pagination-controls")
        self.assertContains(response, "page-btn-disabled")
        self.assertContains(response, "page-num-disabled")

    def test_pagination_controls_hx_select_attribute(self):
        url = reverse("candidate_job_table", args=[self.job_sales_staff.id])
        response = self.client.get(f"{url}?page=1")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'hx-select=".job-candidate-table-inner"')
        self.assertContains(response, "Next")

    def test_post_job_modal_only_in_jobs(self):
        # /admin/jobs/ must have department new job button and post modal
        res_jobs = self.client.get(reverse("job_management"))
        self.assertEqual(res_jobs.status_code, 200)
        self.assertContains(res_jobs, 'open-post-modal-btn')
        self.assertContains(res_jobs, 'id="post-job-modal"')
        self.assertNotContains(res_jobs, 'id="open-post-modal"')

        # /admin/ (dashboard) must NOT have button or modal
        res_dash = self.client.get(reverse("dashboard"))
        self.assertEqual(res_dash.status_code, 200)
        self.assertNotContains(res_dash, 'open-post-modal-btn')
        self.assertNotContains(res_dash, 'id="post-job-modal"')

        # /admin/candidates/ must NOT have button or modal
        res_cand = self.client.get(reverse("candidates"))
        self.assertEqual(res_cand.status_code, 200)
        self.assertNotContains(res_cand, 'open-post-modal-btn')
        self.assertNotContains(res_cand, 'id="post-job-modal"')

    def test_empty_jobs_and_departments_are_excluded(self):
        # Create an active department and job with zero applicants
        empty_job = Job.objects.create(
            title="Empty Position",
            department="Empty Department",
            status="Active",
            job_type="FULL-TIME"
        )

        response = self.client.get(reverse("candidates"))
        self.assertEqual(response.status_code, 200)

        # Department with 0 applicants must NOT be in available_departments
        self.assertNotIn("Empty Department", response.context["available_departments"])

        # Department with 0 applicants must NOT be in department_sections
        dept_names = [d["name"] for d in response.context["department_sections"]]
        self.assertNotIn("Empty Department", dept_names)
        self.assertNotIn(self.hr_dept, dept_names) # HR department also has 0 apps

        # In Sales section, Sales Manager (0 apps) must NOT be in jobs or all_jobs
        sales_section = next(d for d in response.context["department_sections"] if d["name"] == self.sales_dept)
        sales_job_ids = [j.id for j in sales_section["jobs"]]
        sales_all_job_ids = [j["id"] for j in sales_section["all_jobs"]]
        self.assertNotIn(self.job_sales_mgr.id, sales_job_ids)
        self.assertNotIn(self.job_sales_mgr.id, sales_all_job_ids)
        self.assertIn(self.job_sales_staff.id, sales_job_ids)

        # Once an applicant applies to Empty Position, it should now appear
        Application.objects.create(
            job=empty_job,
            first_name="First",
            last_name="Applicant",
            email="first@empty.com",
            phone="1112223333",
            ai_score=88,
            status="Pending"
        )

        response2 = self.client.get(reverse("candidates"))
        self.assertEqual(response2.status_code, 200)
        self.assertIn("Empty Department", response2.context["available_departments"])
        dept_names2 = [d["name"] for d in response2.context["department_sections"]]
        self.assertIn("Empty Department", dept_names2)

    def test_manage_job_get_displays_existing_details_and_qualifications(self):
        # Set requirements and add key qualifications
        self.job_sales_staff.requirements = "Minimum 2 years B2B sales experience"
        self.job_sales_staff.save()
        Requirement.objects.create(job=self.job_sales_staff, text="Lead Generation")
        Requirement.objects.create(job=self.job_sales_staff, text="CRM Mastery")

        url = reverse("manage_job", args=[self.job_sales_staff.id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # Verify general requirements text is populated in textarea
        self.assertIn("Minimum 2 years B2B sales experience", content)
        # Verify key qualifications are rendered in inputs
        self.assertIn("Lead Generation", content)
        self.assertIn("CRM Mastery", content)
        # Verify context contains key_qualifications
        self.assertIn("key_qualifications", response.context)
        self.assertEqual(len(response.context["key_qualifications"]), 2)

    def test_manage_job_post_updates_details_and_qualifications(self):
        url = reverse("manage_job", args=[self.job_sales_staff.id])
        post_data = {
            "title": "Senior Sales Executive",
            "department": "Enterprise Sales",
            "job_type": "FULL-TIME",
            "description": "Lead enterprise client acquisition.",
            "requirements": "5+ years enterprise SaaS experience",
            "status": "Active",
            "key_qualifications": ["Enterprise Sales", "Contract Negotiation", "SaaS"],
        }
        response = self.client.post(url, post_data)
        self.assertRedirects(response, reverse("job_management"))

        self.job_sales_staff.refresh_from_db()
        self.assertEqual(self.job_sales_staff.title, "Senior Sales Executive")
        self.assertEqual(self.job_sales_staff.department, "Enterprise Sales")
        self.assertEqual(self.job_sales_staff.requirements, "5+ years enterprise SaaS experience")
        saved_reqs = list(self.job_sales_staff.requirements_list.values_list("text", flat=True))
        self.assertEqual(saved_reqs, ["Enterprise Sales", "Contract Negotiation", "SaaS"])

    def test_job_management_active_jobs_separated_per_department(self):
        response = self.client.get(reverse("job_management"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("department_sections", response.context)
        dept_sections = response.context["department_sections"]
        dept_names = [d["name"] for d in dept_sections]
        self.assertIn("Sales", dept_names)
        self.assertIn("Human Resources", dept_names)

        sales_sec = next(d for d in dept_sections if d["name"] == "Sales")
        sales_job_ids = [j.id for j in sales_sec["jobs"]]
        self.assertIn(self.job_sales_staff.id, sales_job_ids)
        self.assertIn(self.job_sales_mgr.id, sales_job_ids)
        self.assertEqual(sales_sec["active_count"], 2)

    def test_create_department_creates_model_and_sections(self):
        url = reverse("create_department")
        response = self.client.post(url, {"name": "Engineering"})
        self.assertRedirects(response, reverse("job_management"))
        self.assertTrue(Department.objects.filter(name="Engineering").exists())

        res = self.client.get(reverse("job_management"))
        dept_names = [d["name"] for d in res.context["department_sections"]]
        self.assertIn("Engineering", dept_names)

    def test_create_department_htmx(self):
        url = reverse("create_department")
        response = self.client.post(url, {"name": "Design"}, HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("HX-Trigger"), "closeDeptModal")
        self.assertContains(response, "Design Department")
        self.assertTrue(Department.objects.filter(name="Design").exists())

    def test_department_section_contains_new_job_button(self):
        response = self.client.get(reverse("job_management"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="open-new-department-modal"')
        self.assertContains(response, 'data-department="Sales"')
        self.assertContains(response, 'data-department="Human Resources"')

    def test_manage_job_htmx_get_returns_partial_modal(self):
        url = reverse("manage_job", args=[self.job_sales_staff.id])
        response = self.client.get(url, HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="edit-job-modal"')
        self.assertContains(response, 'id="manage-job-form"')
        self.assertContains(response, 'id="edit-status-toggle"')
        self.assertContains(response, 'status-toggle-card')
        self.assertContains(response, self.job_sales_staff.title)
        self.assertNotContains(response, "<!DOCTYPE html>")

    def test_manage_job_htmx_post_updates_and_swaps_content(self):
        url = reverse("manage_job", args=[self.job_sales_staff.id])
        post_data = {
            "title": "Lead Sales Executive",
            "department": "Global Sales",
            "job_type": "FULL-TIME",
            "description": "Lead global deals.",
            "requirements": "7+ years global B2B experience",
            "status": "Active",
            "key_qualifications": ["Global Deals", "Negotiation"],
        }
        response = self.client.post(url, post_data, HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("HX-Trigger"), "closeEditModal")
        self.assertContains(response, "Global Sales Department")
        self.assertContains(response, "Lead Sales Executive")

        self.job_sales_staff.refresh_from_db()
        self.assertEqual(self.job_sales_staff.title, "Lead Sales Executive")
        self.assertEqual(self.job_sales_staff.department, "Global Sales")

    def test_manage_job_editing_department_does_not_create_new_department_model(self):
        self.assertFalse(Department.objects.filter(name="Brand New Dept").exists())
        url = reverse("manage_job", args=[self.job_sales_staff.id])
        post_data = {
            "title": "Sales Rep",
            "department": "Brand New Dept",
            "job_type": "FULL-TIME",
            "description": "Sales role.",
            "requirements": "Experience required",
            "status": "Active",
        }
        self.client.post(url, post_data)
        self.job_sales_staff.refresh_from_db()
        self.assertEqual(self.job_sales_staff.department, "Brand New Dept")
        # System must NOT create a new Department model record when editing a job's department
        self.assertFalse(Department.objects.filter(name="Brand New Dept").exists())

    def test_minimized_department_section_without_active_jobs(self):
        Department.objects.create(name="Product Design")
        invalidate_hr_cache()
        response = self.client.get(reverse("job_management"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "dept-section-minimized")
        self.assertContains(response, "Product Design Department")
        self.assertContains(response, "0 Active Positions")
        self.assertContains(response, "inactive-jobs-box")

    def test_job_forms_contain_schedule_and_shift(self):
        # Check job management page has schedule and shift in post-job modal
        response = self.client.get(reverse("job_management"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="new-job-schedule"')
        self.assertContains(response, 'id="new-job-shift"')
        self.assertContains(response, 'existing-departments-box')
        self.assertContains(response, 'Sales')
        self.assertContains(response, 'Human Resources')

        # Check edit job modal has schedule and shift
        url = reverse("manage_job", args=[self.job_sales_staff.id])
        edit_response = self.client.get(url, HTTP_HX_REQUEST="true")
        self.assertEqual(edit_response.status_code, 200)
        self.assertContains(edit_response, 'id="edit-modal-schedule"')
        self.assertContains(edit_response, 'id="edit-modal-shift"')

    def test_create_job_saves_schedule_and_shift(self):
        post_data = {
            "title": "Operations Specialist",
            "department": "Operations",
            "job_type": "FULL-TIME",
            "schedule": "Monday to Friday",
            "shift": "8:00 AM - 5:00 PM",
            "description": "Handle day-to-day operations.",
            "requirements": "3+ years operations experience",
            "key_qualifications": ["Supply Chain", "Logistics"],
        }
        response = self.client.post(reverse("create_job"), post_data)
        self.assertRedirects(response, reverse("job_management"))

        job = Job.objects.filter(title="Operations Specialist").first()
        self.assertIsNotNone(job)
        self.assertEqual(job.schedule, "Monday to Friday")
        self.assertEqual(job.shift, "8:00 AM - 5:00 PM")
        self.assertEqual(job.department, "Operations")

    def test_manage_job_updates_schedule_and_shift(self):
        url = reverse("manage_job", args=[self.job_sales_staff.id])
        post_data = {
            "title": "Senior Sales Staff",
            "department": "Sales",
            "job_type": "FULL-TIME",
            "schedule": "Tuesday to Saturday",
            "shift": "9:00 AM - 6:00 PM",
            "description": "Updated description",
            "requirements": "Updated requirements",
            "status": "Active",
            "key_qualifications": ["Negotiation"],
        }
        response = self.client.post(url, post_data, HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)

        self.job_sales_staff.refresh_from_db()
        self.assertEqual(self.job_sales_staff.schedule, "Tuesday to Saturday")
        self.assertEqual(self.job_sales_staff.shift, "9:00 AM - 6:00 PM")

    def test_create_department_oob_updates_existing_dept_list(self):
        url = reverse("create_department")
        response = self.client.post(url, {"name": "Finance"}, HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="existing-dept-chips-list"')
        self.assertContains(response, 'Finance')

    def test_job_management_department_filter_dropdown_renders(self):
        response = self.client.get(reverse("job_management"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'candidates-top-toolbar')
        self.assertContains(response, 'id="deptSelect"')
        self.assertContains(response, 'All Available Departments')
        self.assertContains(response, 'Sales Department')
        self.assertContains(response, 'Human Resources Department')

    def test_job_management_department_filter_filters_sections(self):
        # Filter by Sales department
        url = f"{reverse('job_management')}?department=Sales"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<h2 class="dept-title-text">Sales Department</h2>')
        self.assertNotContains(response, '<h2 class="dept-title-text">Human Resources Department</h2>')
        self.assertContains(response, "Reset Filter")
        self.assertEqual(response.context["selected_department"], "Sales")

    def test_inactive_count_displayed_per_department_section(self):
        # Create an inactive job in Sales
        Job.objects.create(
            title="Archived Sales Lead",
            department="Sales",
            job_type="FULL-TIME",
            status="Inactive"
        )
        invalidate_hr_cache()

        response = self.client.get(reverse("job_management"))
        self.assertEqual(response.status_code, 200)
        # Sales section should show 2 active and 1 inactive
        self.assertContains(response, "<strong>2</strong> Active Positions")
        self.assertContains(response, "<strong>1</strong> Inactive Position")

    def test_req_indicator_removed_from_job_cards(self):
        # Add a requirement to job_sales_staff
        Requirement.objects.create(job=self.job_sales_staff, text="B2B Sales")
        invalidate_hr_cache()

        response = self.client.get(reverse("job_management"))
        self.assertEqual(response.status_code, 200)
        # Should not display the "1 Req" badge in the card meta
        self.assertNotContains(response, "1 Req")
        self.assertNotContains(response, "Reqs")

    def test_candidates_button_disabled_when_zero_applicants(self):
        # job_sales_mgr has 0 applicants; job_sales_staff has 10 applicants
        invalidate_hr_cache()
        response = self.client.get(reverse("job_management"))
        self.assertEqual(response.status_code, 200)

        # For job with 0 applicants: disabled button with tooltip
        self.assertContains(response, '<button type="button" class="btn-job-view" disabled title="No applicants yet for this position">')
        # For job with applicants: link to candidates
        expected_active_link = f'href="{reverse("candidates")}?department=Sales&job={self.job_sales_staff.id}" class="btn-job-view"'
        self.assertContains(response, expected_active_link)
        # Not linked for job_sales_mgr
        unexpected_link = f'href="{reverse("candidates")}?department=Sales&job={self.job_sales_mgr.id}"'
        self.assertNotContains(response, unexpected_link)

    def test_inactive_job_candidates_button_disabled_when_zero_applicants(self):
        inactive_job_no_apps = Job.objects.create(
            title="Archived No Apps",
            department="Sales",
            job_type="FULL-TIME",
            status="Inactive"
        )
        inactive_job_with_apps = Job.objects.create(
            title="Archived With Apps",
            department="Sales",
            job_type="FULL-TIME",
            status="Inactive"
        )
        Application.objects.create(
            job=inactive_job_with_apps,
            first_name="Jane",
            last_name="Doe",
            email="jane@example.com",
            phone="1234567890",
            ai_score=85,
            status="Screening",
        )
        invalidate_hr_cache()

        response = self.client.get(reverse("job_management"))
        self.assertEqual(response.status_code, 200)

        # The inactive job with applicants should have a clickable candidates link
        expected_inactive_link = f'href="{reverse("candidates")}?department=Sales&job={inactive_job_with_apps.id}" class="btn-job-view"'
        self.assertContains(response, expected_inactive_link)

        # The inactive job without applicants should NOT have a clickable candidates link
        unexpected_inactive_link = f'href="{reverse("candidates")}?department=Sales&job={inactive_job_no_apps.id}"'
        self.assertNotContains(response, unexpected_inactive_link)

    def test_sidebar_alert_container_present_above_sidebar_footer(self):
        response = self.client.get(reverse("job_management"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="sidebar-alert-container"')
        self.assertContains(response, 'sidebar-alert-container')
        # Check order: sidebar-alert-container appears before sidebar-footer
        content = response.content.decode("utf-8")
        alert_pos = content.find('id="sidebar-alert-container"')
        footer_pos = content.find('class="sidebar-footer"')
        self.assertTrue(alert_pos > 0 and footer_pos > 0 and alert_pos < footer_pos)

    def test_manage_job_save_redirect_and_htmx_trigger(self):
        url = reverse("manage_job", kwargs={"pk": self.job_sales_staff.pk})
        post_data = {
            "title": "Senior Sales Staff",
            "department": "Sales",
            "job_type": "FULL-TIME",
            "schedule": "Monday to Friday",
            "shift": "8:00 AM - 5:00 PM",
            "description": "Updated description",
            "requirements": "Updated requirements",
            "status": "Inactive",
            "key_qualifications": ["Negotiation"],
        }
        # HTMX submission returns closeEditModal trigger
        hx_response = self.client.post(url, post_data, HTTP_HX_REQUEST="true")
        self.assertEqual(hx_response.status_code, 200)
        self.assertEqual(hx_response.headers.get("HX-Trigger"), "closeEditModal")

        # Standard POST submission redirects to job_management with success message
        post_data["title"] = "Lead Sales Staff"
        std_response = self.client.post(url, post_data)
        self.assertEqual(std_response.status_code, 302)
        follow_response = self.client.get(reverse("job_management"))
        self.assertContains(follow_response, "Changes saved successfully!")

    def test_create_department_htmx_trigger_and_redirect_message(self):
        url = reverse("create_department")
        # HTMX submission triggers closeDeptModal
        hx_response = self.client.post(url, {"name": "Legal"}, HTTP_HX_REQUEST="true")
        self.assertEqual(hx_response.status_code, 200)
        self.assertEqual(hx_response.headers.get("HX-Trigger"), "closeDeptModal")

        # Standard POST redirects with success message
        std_response = self.client.post(url, {"name": "Operations"})
        self.assertEqual(std_response.status_code, 302)
        follow_response = self.client.get(reverse("job_management"))
        self.assertContains(follow_response, "New department created successfully!")

    def test_create_job_htmx_trigger_and_redirect_message(self):
        url = reverse("create_job")
        post_data = {
            "title": "Accountant",
            "department": "Finance",
            "job_type": "FULL-TIME",
            "schedule": "Monday to Friday",
            "shift": "9:00 AM - 5:00 PM",
            "description": "Handle company books",
            "requirements": "CPA license",
            "key_qualifications": ["QuickBooks", "Tax Filing"],
        }
        # HTMX submission triggers closePostModal
        hx_response = self.client.post(url, post_data, HTTP_HX_REQUEST="true")
        self.assertEqual(hx_response.status_code, 200)
        self.assertEqual(hx_response.headers.get("HX-Trigger"), "closePostModal")
        self.assertContains(hx_response, "Accountant")

    def test_post_job_modal_four_column_layout(self):
        """Verify Create New Job Opening modal has a 4-column layout with separated Key Qualifications and Criteria."""
        response = self.client.get(reverse("job_management"))
        self.assertEqual(response.status_code, 200)

        # Modal overlay, wide card, and 4-column grid
        self.assertContains(response, 'id="post-job-modal"')
        self.assertContains(response, 'post-job-card-wide')
        self.assertContains(response, 'four-col-form-grid')

        # 4 Columns
        self.assertContains(response, 'class="form-col-1"')
        self.assertContains(response, 'class="form-col-2"')
        self.assertContains(response, 'class="form-col-3"')
        self.assertContains(response, 'class="form-col-4"')

        # Uniform section title spans
        self.assertContains(response, '<span>Job Details</span>')
        self.assertContains(response, '<span>Job Description</span>')
        self.assertContains(response, '<span>Requirements</span>')
        self.assertContains(response, '<span>Key Qualifications</span>')
        self.assertContains(response, '<span>Criteria</span>')

        # Column 1 fields: title, department, job_type, schedule, shift
        self.assertContains(response, 'id="new-job-title"')
        self.assertContains(response, 'id="new-job-cat"')
        self.assertContains(response, 'id="new-job-type"')
        self.assertContains(response, 'id="new-job-schedule"')
        self.assertContains(response, 'id="new-job-shift"')

        # Column 2 fields: description, requirements, doubled height class
        self.assertContains(response, 'id="new-job-description"')
        self.assertContains(response, 'id="new-job-requirements"')
        self.assertContains(response, 'job-modal-textarea')

        # Column 3 fields: key qualifications
        self.assertContains(response, 'id="key-qualifications-container"')
        self.assertContains(response, 'id="add-key-qualification"')

        # Column 4 fields: criteria weights, total, validation
        self.assertContains(response, 'name="criteria_skills_weight"')
        self.assertContains(response, 'name="criteria_education_weight"')
        self.assertContains(response, 'name="criteria_experience_weight"')
        self.assertContains(response, 'name="criteria_qualification_weight"')
        self.assertContains(response, 'id="criteria-total"')
        self.assertContains(response, 'id="criteria-validation"')

    def test_edit_job_modal_four_column_layout(self):
        """Verify Edit Job Details modal has a 4-column layout with uniform spans and separated Criteria."""
        url = reverse("manage_job", kwargs={"pk": self.job_sales_staff.pk})
        response = self.client.get(url, HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)

        # Modal overlay, wide card, and 4-column grid
        self.assertContains(response, 'id="edit-job-modal"')
        self.assertContains(response, 'post-job-card-wide')
        self.assertContains(response, 'four-col-form-grid')

        # 4 Columns
        self.assertContains(response, 'class="form-col-1"')
        self.assertContains(response, 'class="form-col-2"')
        self.assertContains(response, 'class="form-col-3"')
        self.assertContains(response, 'class="form-col-4"')

        # Uniform section title spans (no "General Information" or "Role Description")
        self.assertContains(response, '<span>Job Details</span>')
        self.assertNotContains(response, '<span>General Information</span>')
        self.assertContains(response, '<span>Job Description</span>')
        self.assertNotContains(response, '<span>Role Description</span>')
        self.assertContains(response, '<span>Requirements</span>')
        self.assertContains(response, '<span>Key Qualifications</span>')
        self.assertContains(response, '<span>Criteria</span>')

        # Column 1 fields: title, department, job_type, schedule, shift, status toggle
        self.assertContains(response, 'id="edit-modal-title"')
        self.assertContains(response, 'id="edit-modal-dept"')
        self.assertContains(response, 'id="edit-modal-type"')
        self.assertContains(response, 'id="edit-modal-schedule"')
        self.assertContains(response, 'id="edit-modal-shift"')
        self.assertContains(response, 'id="edit-status-toggle"')

        # Column 2 fields: description, requirements, doubled height class
        self.assertContains(response, 'id="edit-modal-description"')
        self.assertContains(response, 'id="edit-modal-requirements"')
        self.assertContains(response, 'job-modal-textarea')

        # Column 3 fields: key qualifications
        self.assertContains(response, 'id="key-qualifications-container"')
        self.assertContains(response, 'id="edit-add-key-qualification"')

        # Column 4 fields: criteria weights, total, validation
        self.assertContains(response, 'name="criteria_skills_weight"')
        self.assertContains(response, 'name="criteria_education_weight"')
        self.assertContains(response, 'name="criteria_experience_weight"')
        self.assertContains(response, 'name="criteria_qualification_weight"')
        self.assertContains(response, 'id="edit-criteria-total"')
        self.assertContains(response, 'id="edit-criteria-validation"')

    @patch("jobs.ai.extract_resume_text", return_value="Experienced sales associate with 5 years customer service.")
    @patch("jobs.ai.analyze_resume")
    def test_candidate_detail_auto_reanalyzes_unscreened_candidate(self, mock_analyze, mock_extract):
        """Visiting candidate_detail automatically triggers screening if candidate has 0 score / unprocessed."""
        from django.core.files.uploadedfile import SimpleUploadedFile
        mock_analyze.return_value = {
            "score": 87,
            "match_level": "Proficient",
            "recommendation": "Recommended",
            "summary": "Candidate matches sales staff role.",
            "strengths": ["Strong verbal communication"],
            "weaknesses": [],
            "matched_qualifications": ["Sales experience"],
            "missing_qualifications": [],
            "skills_match": 85,
            "experience_match": 88,
            "education_match": 80,
            "qualification_match": 90,
            "criteria_weights": {"sales": 30},
            "weight_reasoning": {},
        }
        unscreened_app = Application.objects.create(
            job=self.job_sales_staff,
            first_name="Carlos",
            last_name="Gomez",
            email="carlos@test.com",
            phone="09112223333",
            resume=SimpleUploadedFile("carlos.pdf", b"%PDF-1.4 dummy", content_type="application/pdf"),
            ai_score=0,
            resume_processed=False,
            ai_recommendation="Pending Review",
        )
        url = reverse("candidate_detail", kwargs={"pk": unscreened_app.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        unscreened_app.refresh_from_db()
        self.assertEqual(unscreened_app.ai_score, 87)
        self.assertTrue(unscreened_app.resume_processed)
        self.assertEqual(unscreened_app.ai_recommendation, "Recommended")

    def test_candidate_detail_hero_card_4_columns(self):
        """Candidate detail page renders 4 columns in hero card with indicator-only stage card and no dropdown."""
        app = Application.objects.create(
            job=self.job_sales_staff,
            first_name="Marco",
            last_name="Polo",
            email="marco@explorer.com",
            phone="09191234567",
            ai_score=88,
            resume_processed=True,
            status="Screening",
        )
        url = reverse("candidate_detail", kwargs={"pk": app.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        # 4 columns present
        self.assertContains(response, "candidate-hero-4col")
        self.assertContains(response, "hero-col-applicant")
        self.assertContains(response, "hero-col-details")
        self.assertContains(response, "hero-col-stage")
        self.assertContains(response, "hero-col-actions")

        # Verify Column 3 (Stage) appears before Column 4 (Actions)
        content = response.content.decode("utf-8")
        stage_pos = content.find("hero-col-stage")
        actions_pos = content.find("hero-col-actions")
        self.assertTrue(stage_pos > 0 and actions_pos > 0 and stage_pos < actions_pos)

        # Candidate details present in Col 1 & 2
        self.assertContains(response, "marco@explorer.com")
        self.assertContains(response, "09191234567")
        self.assertContains(response, app.application_id)

        # Copy buttons present, no tel: or mailto: links in contact chips
        self.assertContains(response, "btn-copy-chip")
        self.assertContains(response, "copyCandidateContact")
        self.assertNotContains(response, 'href="mailto:')
        self.assertNotContains(response, 'href="tel:')

        # Actions present in Col 4
        self.assertContains(response, "btn-schedule")
        self.assertContains(response, "btn-email")
        self.assertContains(response, "openConfirmScheduleModal")
        self.assertContains(response, "confirmScheduleModal")
        self.assertContains(response, "mail.google.com/mail/?view=cm")
        self.assertNotContains(response, "Updated Profile CV")

        # Stage CTA present in Col 3 (Indicator only, no select dropdown)
        self.assertContains(response, "stage-cta-card")
        self.assertContains(response, "stage-card-screening")
        self.assertNotContains(response, '<select name="status"')

        # Re-analyze with AI button must be removed
        self.assertNotContains(response, "Re-analyze with AI")

    def test_candidate_detail_normalizes_legacy_pending_to_screening(self):
        """Any legacy Pending application is normalized to Screening when loaded."""
        legacy_app = Application.objects.create(
            job=self.job_sales_staff,
            first_name="Legacy",
            last_name="Applicant",
            email="legacy@test.com",
            phone="09198765432",
            ai_score=75,
            resume_processed=True,
            status="Pending",
        )
        url = reverse("candidate_detail", kwargs={"pk": legacy_app.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        legacy_app.refresh_from_db()
        self.assertEqual(legacy_app.status, "Screening")

    def test_schedule_interview_auto_advances_candidate_to_interview_stage(self):
        """Scheduling an interview automatically moves selected applicants from Screening to Interview."""
        app = Application.objects.create(
            job=self.job_sales_staff,
            first_name="Sara",
            last_name="Connor",
            email="sara@future.com",
            phone="09110001111",
            ai_score=94,
            resume_processed=True,
            status="Screening",
        )
        self.assertEqual(app.status, "Screening")
        self.assertFalse(app.interview_scheduled)

        post_data = {
            "interview_type": "HR Interview",
            "interviewer": "John HR Lead",
            "date": "2026-10-15",
            "time": "14:00",
            "location": "Online / Zoom",
            "notes": "Initial interview round.",
            "applicants": [str(app.id)],
        }
        url = reverse("schedule_interview", kwargs={"job_id": self.job_sales_staff.id})
        response = self.client.post(url, post_data)
        self.assertEqual(response.status_code, 302)

        app.refresh_from_db()
        self.assertEqual(app.status, "Interview")
        self.assertTrue(app.interview_scheduled)

    @patch("main.emailer.send_gmail_message")
    def test_send_candidate_email_view(self, mock_send):
        """HR can send direct emails to candidates with Gmail API."""
        mock_send.return_value = {"success": True, "id": "msg_123"}
        app = Application.objects.create(
            job=self.job_sales_staff,
            first_name="Leo",
            last_name="Vinci",
            email="leo@art.com",
            phone="09123456789",
            ai_score=89,
            resume_processed=True,
            status="Screening",
        )
        url = reverse("send_candidate_email", kwargs={"pk": app.pk})
        post_data = {
            "recipient_email": app.email,
            "subject": "Interview Invitation - DBRecruitAI",
            "message": "Dear Leo, we would love to invite you for an interview.",
        }
        response = self.client.post(url, post_data)
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse("candidate_detail", kwargs={"pk": app.pk}))

        mock_send.assert_called_once()
        args, kwargs = mock_send.call_args
        self.assertEqual(kwargs["to_email"], "leo@art.com")
        self.assertEqual(kwargs["subject"], "Interview Invitation - DBRecruitAI")
        self.assertIn("Dear Leo", kwargs["text_content"])

    def test_evaluation_stage_choices_exist(self):
        """Evaluation stage is present in Application.STATUS_CHOICES."""
        status_dict = dict(Application.STATUS_CHOICES)
        self.assertIn("Evaluation", status_dict)
        self.assertEqual(status_dict["Evaluation"], "Evaluation")

    def test_candidate_detail_interview_stage_shows_evaluate_and_hides_schedule(self):
        """In Interview stage, Schedule Interview is hidden and Evaluate Candidate is shown."""
        app = Application.objects.create(
            job=self.job_sales_staff,
            first_name="Ada",
            last_name="Lovelace",
            email="ada@computing.org",
            phone="09181234567",
            ai_score=95,
            resume_processed=True,
            status="Interview",
        )
        url = reverse("candidate_detail", kwargs={"pk": app.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        # Stage indicator should show Interview
        self.assertContains(response, "stage-card-interview")

        # In Interview stage: Schedule button must NOT appear, Evaluate button MUST appear
        self.assertNotContains(response, "Schedule Interview</span>")
        self.assertContains(response, "Evaluate Candidate</span>")
        self.assertContains(response, "btn-evaluate")
        self.assertContains(response, "#candidate-evaluation-section")

        # Candidate Evaluation section must be present on page
        self.assertContains(response, "candidate-evaluation-section")
        self.assertContains(response, "Candidate Interview Evaluation")

    def test_candidate_detail_screening_stage_shows_schedule_interview(self):
        """In Screening stage, Schedule Interview is shown and Evaluate button is not shown in hero actions."""
        app = Application.objects.create(
            job=self.job_sales_staff,
            first_name="Grace",
            last_name="Hopper",
            email="grace@navy.mil",
            phone="09187654321",
            ai_score=92,
            resume_processed=True,
            status="Screening",
        )
        url = reverse("candidate_detail", kwargs={"pk": app.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        self.assertContains(response, "stage-card-screening")
        self.assertContains(response, "Schedule Interview</span>")
        self.assertNotContains(response, "Evaluate Candidate</span>")

    def test_candidate_detail_evaluation_stage_card(self):
        """In Evaluation stage, the stage card indicates Evaluation and action shows Update Evaluation."""
        app = Application.objects.create(
            job=self.job_sales_staff,
            first_name="Alan",
            last_name="Turing",
            email="alan@turing.ac.uk",
            phone="09170001234",
            ai_score=98,
            resume_processed=True,
            status="Evaluation",
        )
        url = reverse("candidate_detail", kwargs={"pk": app.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        self.assertContains(response, "stage-card-evaluation")
        self.assertContains(response, "Update Evaluation</span>")

    def test_evaluate_candidate_view_post_creates_evaluation_and_advances_stage(self):
        """Submitting evaluation creates CandidateEvaluation and transitions candidate to Evaluation stage."""
        app = Application.objects.create(
            job=self.job_sales_staff,
            first_name="Katherine",
            last_name="Johnson",
            email="katherine@nasa.gov",
            phone="09199998888",
            ai_score=96,
            resume_processed=True,
            status="Interview",
        )
        url = reverse("evaluate_candidate", kwargs={"pk": app.pk})
        post_data = {
            "interview_mode": "Face-to-Face",
            "evaluation_date": "2026-10-16",
            "technical_competence": "5",
            "communication_skills": "4",
            "problem_solving": "5",
            "cultural_fit": "5",
            "leadership_potential": "4",
            "strengths_notes": "Brilliant analytical thinking and clear communication.",
            "weaknesses_notes": "None observed.",
            "general_notes": "Highly recommended for immediate hire.",
            "expected_salary": "PHP 70,000",
            "notice_period": "Immediate",
            "availability_date": "Immediately",
            "recommendation": "Strong Hire",
        }
        response = self.client.post(url, post_data)
        self.assertEqual(response.status_code, 302)

        # Status must advance to Evaluation
        app.refresh_from_db()
        self.assertEqual(app.status, "Evaluation")

        # CandidateEvaluation must exist with correct rubric average
        from hr.models import CandidateEvaluation
        evaluation = CandidateEvaluation.objects.get(application=app)
        self.assertEqual(evaluation.interview_mode, "Face-to-Face")
        self.assertEqual(evaluation.recommendation, "Strong Hire")
        self.assertEqual(evaluation.technical_competence, 5)
        # Average: (5 + 4 + 5 + 5 + 4) / 5 = 4.6
        self.assertEqual(float(evaluation.overall_rating), 4.6)

    def test_reports_sidebar_navigation_and_dashboard_view(self):
        """Reports navigation link appears in sidebar and reports dashboard renders successfully."""
        url = reverse("reports")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        # Reports tab in sidebar
        self.assertContains(response, 'href="/hr/reports/"')
        self.assertContains(response, "Reports</span>")

        # Reports dashboard content
        self.assertContains(response, "Candidate Reports")
        self.assertContains(response, "Total Evaluated")
        self.assertContains(response, "Avg Rubric Score")

    def test_reports_subnavigation_renders_all_three_tabs(self):
        """Reports page renders sub navigation with Audit Logs, Cancelled, and Evaluated Candidates."""
        url = reverse("reports")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        # Verify all 3 sub-navigation buttons exist
        self.assertContains(response, "tab-btn-audit")
        self.assertContains(response, "Audit Logs")
        self.assertContains(response, "tab-btn-cancelled")
        self.assertContains(response, "Cancelled (Rejected Applications)")
        self.assertContains(response, "tab-btn-evaluations")
        self.assertContains(response, "Evaluated Candidates")

        # Verify all 3 tab panes exist in DOM
        self.assertContains(response, "tab-pane-audit")
        self.assertContains(response, "tab-pane-cancelled")
        self.assertContains(response, "tab-pane-evaluations")

        # Verify context variables
        self.assertIn("active_tab", response.context)
        self.assertEqual(response.context["active_tab"], "audit")
        self.assertIn("total_audit_logs", response.context)
        self.assertIn("total_cancelled", response.context)
        self.assertIn("total_evaluations", response.context)

    def test_reports_tab_switching_query_param(self):
        """Active tab can be specified via ?tab= URL query parameter."""
        # Cancelled tab
        url_cancelled = f"{reverse('reports')}?tab=cancelled"
        resp_cancelled = self.client.get(url_cancelled)
        self.assertEqual(resp_cancelled.status_code, 200)
        self.assertEqual(resp_cancelled.context["active_tab"], "cancelled")

        # Evaluated candidates tab
        url_eval = f"{reverse('reports')}?tab=evaluations"
        resp_eval = self.client.get(url_eval)
        self.assertEqual(resp_eval.status_code, 200)
        self.assertEqual(resp_eval.context["active_tab"], "evaluations")

        # Audit logs tab
        url_audit = f"{reverse('reports')}?tab=audit"
        resp_audit = self.client.get(url_audit)
        self.assertEqual(resp_audit.status_code, 200)
        self.assertEqual(resp_audit.context["active_tab"], "audit")

    def test_audit_log_tracking_and_filtering(self):
        """HR actions create AuditLog entries and filters return matching logs."""
        from hr.models import AuditLog

        # Create a job via POST to verify audit logging
        create_job_url = reverse("create_job")
        self.client.post(create_job_url, {
            "title": "QA Automation Lead",
            "department": "Engineering",
            "job_type": "FULL-TIME",
            "schedule": "Monday to Friday",
            "shift": "Day Shift",
            "description": "Leading QA teams.",
            "requirements": "5+ years QA experience.",
            "key_qualifications": ["Python", "Selenium"],
        })
        self.assertTrue(
            AuditLog.objects.filter(action="JOB_CREATED", target_repr="QA Automation Lead").exists()
        )

        # Update candidate status to Rejected
        candidate = self.sales_apps[0]
        status_url = reverse("update_application_status", args=[candidate.pk])
        self.client.post(status_url, {"status": "Rejected"})

        self.assertTrue(
            AuditLog.objects.filter(action="REJECT_APPLICATION", target_id=str(candidate.pk)).exists()
        )

        # Test filtering by action
        filter_url = f"{reverse('reports')}?tab=audit&audit_action=REJECT_APPLICATION"
        resp = self.client.get(filter_url)
        self.assertEqual(resp.status_code, 200)
        for log in resp.context["audit_logs"]:
            self.assertEqual(log.action, "REJECT_APPLICATION")

        # Test search
        search_url = f"{reverse('reports')}?tab=audit&audit_search={candidate.first_name}"
        resp_search = self.client.get(search_url)
        self.assertEqual(resp_search.status_code, 200)
        self.assertTrue(any(candidate.first_name in log.target_repr for log in resp_search.context["audit_logs"]))

    def test_cancelled_applications_tab_and_restore(self):
        """Cancelled tab lists rejected candidates and allows restoring them back to Screening."""
        from hr.models import AuditLog

        # Reject a candidate
        rejected_app = Application.objects.create(
            job=self.job_sales_staff,
            first_name="RejectedApplicant",
            last_name="TestPerson",
            email="rejected_applicant@test.com",
            phone="09998887777",
            ai_score=45,
            status="Rejected",
        )

        # Check they appear on cancelled tab
        url = f"{reverse('reports')}?tab=cancelled"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "RejectedApplicant")
        self.assertContains(response, "#" + rejected_app.application_id)

        # Restore candidate back to Screening
        restore_url = reverse("restore_candidate", args=[rejected_app.pk])
        post_resp = self.client.post(restore_url, {"target_stage": "Screening"}, follow=True)
        self.assertEqual(post_resp.status_code, 200)

        rejected_app.refresh_from_db()
        self.assertEqual(rejected_app.status, "Screening")

        # Verify audit log was recorded for the restoration
        self.assertTrue(
            AuditLog.objects.filter(
                action="STATUS_CHANGE",
                target_id=str(rejected_app.pk),
                details__contains="restored"
            ).exists()
        )

    def test_interview_tab_renders_evaluation_section_grouped_by_department(self):
        """Interviews tab renders candidates ready for evaluation grouped by department and position."""
        from hr.models import Interview
        app = Application.objects.create(
            job=self.job_sales_staff,
            first_name="Ada",
            last_name="Lovelace",
            email="ada@computing.org",
            phone="09112223333",
            ai_score=95,
            resume_processed=True,
            status="Interview",
            interview_scheduled=True,
        )
        interview = Interview.objects.create(
            interview_type="Technical Interview",
            interviewer="Grace Hopper",
            date="2026-10-20",
            time="10:00:00",
            location="Room 401",
            status="Scheduled",
        )
        interview.applicants.add(app)

        url = reverse("interviews")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        # Section header and content
        self.assertContains(response, "Candidates Ready for Evaluation")
        self.assertContains(response, f"{self.job_sales_staff.department} Department")
        self.assertContains(response, self.job_sales_staff.title)
        self.assertContains(response, "Ada")
        self.assertContains(response, "Lovelace")
        self.assertContains(response, "Evaluate")

    def test_start_candidate_evaluation_transitions_interview_to_ongoing(self):
        """Starting candidate evaluation transitions scheduled interview to Ongoing."""
        from hr.models import Interview
        app = Application.objects.create(
            job=self.job_sales_staff,
            first_name="Alan",
            last_name="Turing",
            email="alan@turing.ac.uk",
            phone="09123456789",
            ai_score=92,
            resume_processed=True,
            status="Interview",
            interview_scheduled=True,
        )
        interview = Interview.objects.create(
            interview_type="HR Interview",
            interviewer="HR Staff",
            date="2026-10-21",
            time="14:00:00",
            status="Scheduled",
        )
        interview.applicants.add(app)

        url = reverse("start_candidate_evaluation", kwargs={"pk": app.pk})
        response = self.client.post(url, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("status"), "Ongoing")

        interview.refresh_from_db()
        self.assertEqual(interview.status, "Ongoing")

    def test_start_candidate_evaluation_redirects_for_standard_browser_request(self):
        """Standard browser click/GET on Evaluate redirects to candidate detail evaluation section."""
        from hr.models import Interview
        app = Application.objects.create(
            job=self.job_sales_staff,
            first_name="Charles",
            last_name="Babbage",
            email="charles@babbage.org",
            phone="09112223333",
            ai_score=88,
            resume_processed=True,
            status="Interview",
            interview_scheduled=True,
        )
        interview = Interview.objects.create(
            interview_type="HR Interview",
            interviewer="HR Staff",
            date="2026-10-21",
            time="15:00:00",
            status="Scheduled",
        )
        interview.applicants.add(app)

        url = reverse("start_candidate_evaluation", kwargs={"pk": app.pk})
        # Simulate browser navigation with standard browser Accept header
        response = self.client.get(
            url,
            HTTP_ACCEPT="text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"
        )
        expected_redirect = f"{reverse('candidate_detail', kwargs={'pk': app.pk})}?evaluate=1#candidate-evaluation-section"
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, expected_redirect)

        # Confirm evaluation state and interview status transitioned to Ongoing
        interview.refresh_from_db()
        self.assertEqual(interview.status, "Ongoing")
        self.assertTrue(hasattr(app, "evaluation") and app.evaluation.status == "Draft")

    def test_cancel_candidate_evaluation_reverts_interview_to_scheduled(self):
        """Canceling candidate evaluation modal reverts ongoing interview back to Scheduled."""
        from hr.models import Interview
        app = Application.objects.create(
            job=self.job_sales_staff,
            first_name="Margaret",
            last_name="Hamilton",
            email="margaret@mit.edu",
            phone="09133334444",
            ai_score=99,
            resume_processed=True,
            status="Interview",
            interview_scheduled=True,
        )
        interview = Interview.objects.create(
            interview_type="Final Interview",
            interviewer="Lead Architect",
            date="2026-10-22",
            time="11:00:00",
            status="Ongoing",
        )
        interview.applicants.add(app)

        url = reverse("cancel_candidate_evaluation", kwargs={"pk": app.pk})
        response = self.client.post(url, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("status"), "Scheduled")

        interview.refresh_from_db()
        self.assertEqual(interview.status, "Scheduled")

    def test_saving_evaluation_transitions_interview_to_completed_and_redirects_to_interviews(self):
        """Saving evaluation transitions interview status to Completed and redirects to interviews."""
        from hr.models import Interview, CandidateEvaluation
        app = Application.objects.create(
            job=self.job_sales_staff,
            first_name="Claude",
            last_name="Shannon",
            email="claude@belllabs.com",
            phone="09144445555",
            ai_score=97,
            resume_processed=True,
            status="Interview",
            interview_scheduled=True,
        )
        interview = Interview.objects.create(
            interview_type="Technical Interview",
            interviewer="Senior Evaluator",
            date="2026-10-23",
            time="09:30:00",
            status="Ongoing",
        )
        interview.applicants.add(app)

        url = reverse("evaluate_candidate", kwargs={"pk": app.pk})
        post_data = {
            "redirect_to": "interviews",
            "interview_mode": "Online",
            "evaluation_date": "2026-10-23",
            "technical_competence": "5",
            "communication_skills": "5",
            "problem_solving": "5",
            "cultural_fit": "4",
            "leadership_potential": "4",
            "strengths_notes": "Exceptional mathematical and logic skills.",
            "weaknesses_notes": "None.",
            "general_notes": "Outstanding evaluation session.",
            "recommendation": "Strong Hire",
        }
        response = self.client.post(url, post_data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("interviews"))

        # Interview status must be Completed
        interview.refresh_from_db()
        self.assertEqual(interview.status, "Completed")

        # Application status must be Evaluation
        app.refresh_from_db()
        self.assertEqual(app.status, "Evaluation")

        # CandidateEvaluation must be recorded with Completed status
        evaluation = CandidateEvaluation.objects.get(application=app)
        self.assertEqual(evaluation.status, "Completed")
        self.assertEqual(evaluation.interview, interview)
        self.assertEqual(float(evaluation.overall_rating), 4.6)

    def test_multi_candidate_session_evaluates_candidates_independently(self):
        """When an interview session has multiple candidates, evaluating one does not affect the others."""
        from hr.models import Interview, CandidateEvaluation
        app1 = Application.objects.create(
            job=self.job_sales_staff,
            first_name="Gabriel",
            last_name="Navarro",
            email="gabriel@example.com",
            phone="09111111111",
            ai_score=94,
            resume_processed=True,
            status="Interview",
            interview_scheduled=True,
        )
        app2 = Application.objects.create(
            job=self.job_sales_staff,
            first_name="Francis",
            last_name="Tan",
            email="francis@example.com",
            phone="09222222222",
            ai_score=94,
            resume_processed=True,
            status="Interview",
            interview_scheduled=True,
        )
        # Shared interview session
        interview = Interview.objects.create(
            interview_type="HR Interview",
            interviewer="Maria Santos",
            date="2026-10-25",
            time="08:30:00",
            location="HR Conference Area",
            status="Scheduled",
        )
        interview.applicants.set([app1, app2])

        # 1. Initially both are Scheduled
        resp = self.client.get(reverse("interviews"))
        self.assertEqual(resp.status_code, 200)

        # 2. Start evaluating Gabriel (app1)
        start_resp = self.client.post(reverse("start_candidate_evaluation", kwargs={"pk": app1.pk}), HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(start_resp.status_code, 200)

        # Shared interview session is now Ongoing
        interview.refresh_from_db()
        self.assertEqual(interview.status, "Ongoing")

        # In interviews view, app1 must be Ongoing, but app2 MUST STILL BE Scheduled!
        resp2 = self.client.get(reverse("interviews"))
        dept_data = resp2.context["evaluation_departments"]
        sales_job = next(j for d in dept_data for j in d["jobs"] if j["job"].id == self.job_sales_staff.id)
        cand1 = next(a for a in sales_job["applicants"] if a.id == app1.id)
        cand2 = next(a for a in sales_job["applicants"] if a.id == app2.id)

        self.assertEqual(cand1.candidate_status, "Ongoing")
        self.assertEqual(cand2.candidate_status, "Scheduled")

        # 3. Complete evaluation for Gabriel (app1)
        eval_post = {
            "redirect_to": "interviews",
            "interview_mode": "Face-to-Face",
            "evaluation_date": "2026-10-25",
            "technical_competence": "4",
            "communication_skills": "4",
            "problem_solving": "4",
            "cultural_fit": "4",
            "leadership_potential": "4",
            "recommendation": "Hire",
        }
        self.client.post(reverse("evaluate_candidate", kwargs={"pk": app1.pk}), eval_post)

        # Interview session is STILL Ongoing because Francis (app2) is not completed yet!
        interview.refresh_from_db()
        self.assertEqual(interview.status, "Ongoing")

        resp3 = self.client.get(reverse("interviews"))
        dept_data3 = resp3.context["evaluation_departments"]
        sales_job3 = next(j for d in dept_data3 for j in d["jobs"] if j["job"].id == self.job_sales_staff.id)
        cand1_after = next(a for a in sales_job3["applicants"] if a.id == app1.id)
        cand2_after = next(a for a in sales_job3["applicants"] if a.id == app2.id)

        self.assertEqual(cand1_after.candidate_status, "Completed")
        self.assertEqual(cand2_after.candidate_status, "Scheduled")

        # 4. Now complete evaluation for Francis (app2)
        self.client.post(reverse("evaluate_candidate", kwargs={"pk": app2.pk}), eval_post)

        # Now that ALL applicants in this interview are completed, interview session is Completed!
        interview.refresh_from_db()
        self.assertEqual(interview.status, "Completed")

        resp4 = self.client.get(reverse("interviews"))
        dept_data4 = resp4.context["evaluation_departments"]
        sales_job4 = next(j for d in dept_data4 for j in d["jobs"] if j["job"].id == self.job_sales_staff.id)
        cand1_final = next(a for a in sales_job4["applicants"] if a.id == app1.id)
        cand2_final = next(a for a in sales_job4["applicants"] if a.id == app2.id)

        self.assertEqual(cand1_final.candidate_status, "Completed")
        self.assertEqual(cand2_final.candidate_status, "Completed")

    def test_interview_sub_navigation_renders_all_three_tabs_and_removes_old_manage_sessions(self):
        """Interviews page renders the 3 horizontal sub-nav tabs and does not contain the old manage sessions section."""
        response = self.client.get(reverse("interviews"))
        self.assertEqual(response.status_code, 200)

        # 3 horizontal sub-nav tabs
        self.assertContains(response, "interview-subnav-tabs")
        self.assertContains(response, "Schedules & Overview")
        self.assertContains(response, "Candidates Waiting for Interview")
        self.assertContains(response, "Candidates Ready for Evaluation")

        # 3 tab panes
        self.assertContains(response, "tab-pane-schedules")
        self.assertContains(response, "tab-pane-waiting")
        self.assertContains(response, "tab-pane-evaluations")

        # Old Manage sessions section is removed
        self.assertNotContains(response, "interview-session-box")
        self.assertNotContains(response, "interview-manage-btn")

    def test_today_schedule_lists_only_departments_and_positions_with_redirect_button(self):
        """Today's Interview Schedule lists only Department and Positions with a button redirecting to Evaluation."""
        from django.utils import timezone
        today = timezone.localdate()

        app = Application.objects.create(
            job=self.job_sales_staff,
            first_name="Margaret",
            last_name="Hamilton",
            email="margaret@nasa.gov",
            phone="09199887766",
            ai_score=97,
            resume_processed=True,
            status="Interview",
            interview_scheduled=True,
        )
        intv = Interview.objects.create(
            interview_type="Technical Interview",
            interviewer="Grace Hopper",
            date=today,
            time="14:00:00",
            location="Apollo Room",
            status="Scheduled",
        )
        intv.applicants.add(app)

        response = self.client.get(reverse("interviews"))
        self.assertEqual(response.status_code, 200)

        # Today's schedule should list Department & Position
        self.assertContains(response, "Today's Interview Schedule")
        self.assertContains(response, f"{self.job_sales_staff.department} Department")
        self.assertContains(response, self.job_sales_staff.title)
        self.assertContains(response, "Go to Evaluation")
        self.assertContains(response, f"goToEvaluation('{self.job_sales_staff.department.lower()}', '{self.job_sales_staff.id}')")

    def test_screening_stage_candidate_profile_confirmation_modal_and_move_to_waiting(self):
        """Clicking Schedule Interview on screening candidate opens confirmation modal, and confirming lists applicant in waiting."""
        app = Application.objects.create(
            job=self.job_sales_staff,
            first_name="Katherine",
            last_name="Johnson",
            email="katherine@nasa.gov",
            phone="09195554433",
            ai_score=99,
            resume_processed=True,
            status="Screening",
        )

        # 1. Profile GET contains modal trigger
        detail_url = reverse("candidate_detail", kwargs={"pk": app.pk})
        resp = self.client.get(detail_url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "openConfirmScheduleModal()")
        self.assertContains(resp, "confirmScheduleModal")
        self.assertContains(resp, reverse("move_to_interview_waiting", kwargs={"pk": app.pk}))

        # 2. POST to move_to_interview_waiting
        move_url = reverse("move_to_interview_waiting", kwargs={"pk": app.pk})
        post_resp = self.client.post(move_url)
        self.assertRedirects(post_resp, f"{reverse('interviews')}?tab=waiting")

        app.refresh_from_db()
        self.assertEqual(app.status, "Shortlisted")
        self.assertFalse(app.interview_scheduled)

        # 3. Interviews GET now shows Katherine under Candidates Waiting for Interview
        intv_resp = self.client.get(f"{reverse('interviews')}?tab=waiting")
        self.assertContains(intv_resp, "Katherine")
        self.assertContains(intv_resp, "Johnson")
        self.assertContains(intv_resp, "Ready to Schedule")

    def test_candidates_waiting_for_interview_schedule_action(self):
        """HR can schedule an interview for an applicant waiting in Candidates Waiting for Interview."""
        app = Application.objects.create(
            job=self.job_sales_staff,
            first_name="Dorothy",
            last_name="Vaughan",
            email="dorothy@nasa.gov",
            phone="09191112233",
            ai_score=96,
            resume_processed=True,
            status="Interview",
            interview_scheduled=False,
        )

        schedule_post_data = {
            "applicant_id": app.id,
            "interview_type": "Technical Interview",
            "interviewer": "Admin User",
            "date": "2026-10-25",
            "time": "11:00",
            "location": "Google Meet Link: https://meet.google.com/abc-defg-hij",
            "notes": "Bring portfolio",
        }

        resp = self.client.post(reverse("schedule_candidate_interview"), schedule_post_data)
        self.assertRedirects(resp, f"{reverse('interviews')}?tab=evaluations")

        app.refresh_from_db()
        self.assertTrue(app.interview_scheduled)
        self.assertEqual(app.status, "Interview")

        # Newly scheduled interview exists and links Dorothy
        intv = Interview.objects.filter(applicants=app).first()
        self.assertIsNotNone(intv)
        self.assertEqual(intv.interview_type, "Technical Interview")
        self.assertEqual(intv.location, "Google Meet Link: https://meet.google.com/abc-defg-hij")

        # Dorothy now appears in Candidates Ready for Evaluation
        eval_resp = self.client.get(f"{reverse('interviews')}?tab=evaluations")
        self.assertContains(eval_resp, "Dorothy")
        self.assertContains(eval_resp, "Vaughan")
        self.assertContains(eval_resp, "Evaluate")

    def test_reschedule_and_cancel_candidate_interview_with_notes(self):
        """HR can reschedule or cancel an interview recording notes per applicant."""
        app = Application.objects.create(
            job=self.job_sales_staff,
            first_name="Mary",
            last_name="Jackson",
            email="mary@nasa.gov",
            phone="09194445566",
            ai_score=95,
            resume_processed=True,
            status="Interview",
            interview_scheduled=True,
        )
        intv = Interview.objects.create(
            interview_type="HR Interview",
            interviewer="Admin User",
            date="2026-10-22",
            time="10:00:00",
            location="Room 101",
            notes="Initial slot",
            status="Scheduled",
        )
        intv.applicants.add(app)

        # 1. Reschedule with notes
        resched_url = reverse("reschedule_candidate_interview", kwargs={"pk": app.pk})
        resched_data = {
            "date": "2026-10-26",
            "time": "14:30",
            "location": "Room 202",
            "interviewer": "Admin User",
            "reschedule_notes": "Candidate requested postponement due to travel.",
        }
        resched_resp = self.client.post(resched_url, resched_data)
        self.assertRedirects(resched_resp, f"{reverse('interviews')}?tab=waiting")

        intv.refresh_from_db()
        self.assertEqual(str(intv.date), "2026-10-26")
        self.assertEqual(str(intv.time), "14:30:00")
        self.assertEqual(intv.status, "Rescheduled")
        self.assertIn("Candidate requested postponement", intv.notes)

        # 2. Cancel interview with notes
        cancel_url = reverse("cancel_candidate_interview", kwargs={"pk": app.pk})
        cancel_data = {
            "cancel_notes": "Candidate declined the position due to distance.",
            "cancel_action": "cancel_interview",
        }
        cancel_resp = self.client.post(cancel_url, cancel_data)
        self.assertRedirects(cancel_resp, f"{reverse('interviews')}?tab=waiting")

        app.refresh_from_db()
        self.assertFalse(app.interview_scheduled)
        intv.refresh_from_db()
        self.assertIn("Candidate declined the position", intv.notes)

    def test_evaluate_candidate_button_links_directly_to_candidate_evaluation_section(self):
        """In Candidates Ready for Evaluation, Evaluate Candidate links directly to candidate profile evaluation section."""
        app = Application.objects.create(
            job=self.job_sales_staff,
            first_name="Hedy",
            last_name="Lamarr",
            email="hedy@patents.gov",
            phone="09193332211",
            ai_score=94,
            resume_processed=True,
            status="Interview",
            interview_scheduled=True,
        )
        intv = Interview.objects.create(
            interview_type="HR Interview",
            interviewer="Admin User",
            date="2026-10-24",
            time="09:00:00",
            location="Room 303",
            status="Scheduled",
        )
        intv.applicants.add(app)

        resp = self.client.get(f"{reverse('interviews')}?tab=evaluations")
        self.assertEqual(resp.status_code, 200)

        # Evaluate button links to start_candidate_evaluation
        self.assertContains(resp, reverse("start_candidate_evaluation", kwargs={"pk": app.pk}))
        # Profile link is also present
        self.assertContains(resp, reverse("candidate_detail", kwargs={"pk": app.pk}))

    def test_batch_schedule_interview_by_job_modal_action(self):
        """Batch scheduling by job position schedules all selected applicants and redirects to evaluations."""
        app1 = Application.objects.create(
            job=self.job_sales_staff,
            first_name="Katherine",
            last_name="Johnson",
            email="katherine@nasa.gov",
            phone="09191112233",
            ai_score=97,
            resume_processed=True,
            status="Interview",
            interview_scheduled=False,
        )
        app2 = Application.objects.create(
            job=self.job_sales_staff,
            first_name="Annie",
            last_name="Easley",
            email="annie@nasa.gov",
            phone="09192223344",
            ai_score=93,
            resume_processed=True,
            status="Interview",
            interview_scheduled=False,
        )

        batch_url = reverse("schedule_interview", kwargs={"job_id": self.job_sales_staff.pk})
        post_data = {
            "interview_type": "Technical Interview",
            "interviewer": "Admin User",
            "date": "2026-10-28",
            "time": "11:00",
            "location": "Google Meet Link: https://meet.google.com/test-batch",
            "notes": "Group screening session",
            "applicants": [app1.pk, app2.pk],
        }
        response = self.client.post(batch_url, post_data)
        self.assertRedirects(response, f"{reverse('interviews')}?tab=evaluations")

        app1.refresh_from_db()
        app2.refresh_from_db()
        self.assertTrue(app1.interview_scheduled)
        self.assertTrue(app2.interview_scheduled)
        self.assertEqual(app1.status, "Interview")
        self.assertEqual(app2.status, "Interview")

        intv = Interview.objects.filter(applicants=app1).first()
        self.assertIsNotNone(intv)
        self.assertIn(app2, intv.applicants.all())
        self.assertEqual(intv.interview_type, "Technical Interview")

    def test_evaluations_tab_shows_manage_and_evaluate_buttons_and_no_ai_rating_columns(self):
        """In Candidates Ready for Evaluation, candidates have Evaluate and Manage buttons, combined modal, and no AI/Rating columns."""
        app = Application.objects.create(
            job=self.job_sales_staff,
            first_name="Margaret",
            last_name="Hamilton",
            email="margaret@mit.edu",
            phone="09198887766",
            ai_score=99,
            resume_processed=True,
            status="Interview",
            interview_scheduled=True,
        )
        intv = Interview.objects.create(
            interview_type="Initial Interview",
            interviewer="Admin User",
            date="2026-10-25",
            time="10:00:00",
            location="Room 401",
            status="Scheduled",
        )
        intv.applicants.add(app)

        resp = self.client.get(f"{reverse('interviews')}?tab=evaluations")
        self.assertEqual(resp.status_code, 200)

        # Evaluate button
        self.assertContains(resp, "<span>Evaluate</span>")
        # Combined Manage button and modal
        self.assertContains(resp, "<span>Manage</span>")
        self.assertContains(resp, 'id="manageInterviewModal"')
        self.assertNotContains(resp, 'id="rescheduleApplicantModal"')
        self.assertNotContains(resp, 'id="cancelApplicantModal"')

        # Columns removed in evaluations table: AI Score and Evaluation Rating
        self.assertNotContains(resp, "Evaluation Rating")
        self.assertNotContains(resp, '<th class="th-rating"')

        content_str = resp.content.decode("utf-8")
        self.assertIn("Candidate Interview Evaluations", content_str)
        eval_table_snippet = content_str.split("Candidate Interview Evaluations")[1].split("</table>")[0]
        self.assertNotIn("AI Score", eval_table_snippet)
        self.assertNotIn("th-score", eval_table_snippet)
        self.assertNotIn("th-rating", eval_table_snippet)

    def test_rescheduled_interview_shows_rescheduled_status_and_note_modal(self):
        """Rescheduled interviews display RESCHEDULED status badge, Note popup link, and note modal."""
        app = Application.objects.create(
            job=self.job_sales_staff,
            first_name="Katherine",
            last_name="Johnson",
            email="katherine@nasa.gov",
            phone="09192223344",
            ai_score=98,
            resume_processed=True,
            status="Interview",
            interview_scheduled=True,
        )
        intv = Interview.objects.create(
            interview_type="HR Interview",
            interviewer="Admin User",
            date="2026-10-25",
            time="11:00:00",
            location="Room 501",
            status="Scheduled",
        )
        intv.applicants.add(app)

        # Reschedule candidate
        resched_url = reverse("reschedule_candidate_interview", kwargs={"pk": app.pk})
        self.client.post(resched_url, {
            "date": "2026-10-29",
            "time": "15:00",
            "location": "Room 502",
            "interviewer": "Admin User",
            "reschedule_notes": "Candidate had urgent family emergency.",
            "next_tab": "evaluations",
        })

        intv.refresh_from_db()
        self.assertEqual(intv.status, "Rescheduled")

        resp = self.client.get(f"{reverse('interviews')}?tab=evaluations")
        self.assertEqual(resp.status_code, 200)
        # Verify RESCHEDULED badge and Note button
        self.assertContains(resp, "status-rescheduled")
        self.assertContains(resp, "RESCHEDULED")
        self.assertContains(resp, "openRescheduleNoteModal")
        self.assertContains(resp, "View Note")
        self.assertContains(resp, 'id="rescheduleNoteModal"')

    def test_job_candidate_search_displays_true_rank_number(self):
        """HTMX search for a candidate displays their true overall rank in the job, not renumbered #1."""
        # self.sales_apps has 10 applicants sorted 99 down to 90.
        # Index 5 has score 94, which is Rank 6 among all 10 applicants.
        target_app = self.sales_apps[5]
        url = reverse("candidate_job_table", args=[self.job_sales_staff.id])
        resp = self.client.get(f"{url}?search={target_app.first_name}")
        self.assertEqual(resp.status_code, 200)

        table_data = resp.context["table_data"]
        self.assertTrue(table_data["is_search"])
        self.assertEqual(len(table_data["candidates"]), 1)
        # Verify the candidate's table_rank is true rank 6, not 1
        self.assertEqual(table_data["candidates"][0].table_rank, 6)
        # Check rendered HTML contains #6
        self.assertContains(resp, "#6")
        self.assertNotContains(resp, "#1</span>")

    def test_candidate_detail_displays_ai_ranking_beside_role(self):
        """Candidate detail page renders candidate AI rank beside Role in Application Details."""
        # self.sales_apps has 10 applicants; index 0 has score 99 (Rank #1)
        top_app = self.sales_apps[0]
        url = reverse("candidate_detail", kwargs={"pk": top_app.pk})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

        self.assertEqual(resp.context["candidate_rank"], 1)
        self.assertEqual(resp.context["total_job_applicants"], 10)
        self.assertContains(resp, "applicant-ai-rank-badge")
        self.assertContains(resp, "Rank #1")
        self.assertContains(resp, "of 10")

    def test_candidate_detail_displays_interview_schedule_in_stage_card(self):
        """For candidate in Interview stage with scheduled session, date and time appear in Candidate Stage."""
        app = Application.objects.create(
            job=self.job_sales_staff,
            first_name="Rosalind",
            last_name="Franklin",
            email="rosalind@dna.org",
            phone="09181112233",
            ai_score=97,
            status="Interview",
            interview_scheduled=True,
        )
        intv = Interview.objects.create(
            interview_type="Panel Interview",
            interviewer="Admin User",
            date="2026-11-15",
            time="14:30:00",
            location="Room 303 / Google Meet",
            status="Scheduled",
        )
        intv.applicants.add(app)

        url = reverse("candidate_detail", kwargs={"pk": app.pk})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

        self.assertIsNotNone(resp.context["scheduled_interview"])
        self.assertContains(resp, "Nov 15, 2026")
        self.assertContains(resp, "2:30 PM")
        self.assertContains(resp, "Panel Interview")
        self.assertContains(resp, "Room 303 / Google Meet")

    def test_candidate_detail_evaluation_form_visibility_toggle(self):
        """Evaluation form is hidden with placeholder shown by default, and displayed with ?evaluate=1."""
        app = Application.objects.create(
            job=self.job_sales_staff,
            first_name="Dorothy",
            last_name="Vaughan",
            email="dorothy@nasa.gov",
            phone="09183334455",
            ai_score=94,
            status="Interview",
            interview_scheduled=True,
        )
        url = reverse("candidate_detail", kwargs={"pk": app.pk})

        # Default GET: form is hidden, placeholder banner is displayed
        resp_default = self.client.get(url)
        self.assertEqual(resp_default.status_code, 200)
        self.assertFalse(resp_default.context["show_eval_form"])
        self.assertContains(resp_default, "Candidate Interview Evaluation Not Yet Initiated")
        self.assertContains(resp_default, 'id="eval-pending-card" class="eval-pending-box" style="display: block;')
        self.assertContains(resp_default, 'id="eval-form-card" class="eval-form-container" style="display: none;"')

        # GET with ?evaluate=1: form is displayed
        resp_eval = self.client.get(f"{url}?evaluate=1")
        self.assertEqual(resp_eval.status_code, 200)
        self.assertTrue(resp_eval.context["show_eval_form"])
        self.assertContains(resp_eval, 'id="eval-pending-card" class="eval-pending-box" style="display: none;')
        self.assertContains(resp_eval, 'id="eval-form-card" class="eval-form-container" style="display: block;"')

    def test_candidate_detail_shortlisted_stage_card(self):
        """Shortlisted candidate displays Shortlisted stage card and waiting schedule footer."""
        app = Application.objects.create(
            job=self.job_sales_staff,
            first_name="Hedy",
            last_name="Lamarr",
            email="hedy@inventor.org",
            phone="09185556677",
            ai_score=93,
            status="Shortlisted",
        )
        url = reverse("candidate_detail", kwargs={"pk": app.pk})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

        self.assertContains(resp, "stage-card-shortlisted")
        self.assertContains(resp, "Candidate has been shortlisted for interview. Waiting for session scheduling.")
        self.assertContains(resp, "Waiting for Schedule")

    def test_batch_schedule_interview_with_dedicated_and_default_times(self):
        """Batch scheduling assigns dedicated time when provided, or defaults to the start time."""
        app1 = Application.objects.create(
            job=self.job_sales_staff,
            first_name="Dorothy",
            last_name="Vaughan",
            email="dorothy@nasa.gov",
            phone="09193334455",
            ai_score=95,
            resume_processed=True,
            status="Shortlisted",
            interview_scheduled=False,
        )
        app2 = Application.objects.create(
            job=self.job_sales_staff,
            first_name="Mary",
            last_name="Jackson",
            email="mary@nasa.gov",
            phone="09194445566",
            ai_score=91,
            resume_processed=True,
            status="Shortlisted",
            interview_scheduled=False,
        )

        batch_url = reverse("schedule_interview", kwargs={"job_id": self.job_sales_staff.pk})
        post_data = {
            "interview_type": "Technical Interview",
            "interviewer": "Admin User",
            "date": "2026-11-05",
            "time": "09:00",
            "location": "Room 201",
            "notes": "Dedicated times test",
            "applicants": [app1.pk, app2.pk],
            f"applicant_time_{app1.pk}": "09:30",
            f"applicant_time_{app2.pk}": "",
        }
        resp = self.client.post(batch_url, post_data)
        self.assertRedirects(resp, f"{reverse('interviews')}?tab=evaluations")

        app1.refresh_from_db()
        app2.refresh_from_db()
        self.assertTrue(app1.interview_scheduled)
        self.assertTrue(app2.interview_scheduled)
        self.assertEqual(app1.status, "Interview")
        self.assertEqual(app2.status, "Interview")

        intv1 = app1.interview.first()
        intv2 = app2.interview.first()
        self.assertIsNotNone(intv1)
        self.assertIsNotNone(intv2)
        self.assertEqual(intv1.time.strftime("%H:%M"), "09:30")
        self.assertEqual(intv2.time.strftime("%H:%M"), "09:00")

    def test_interview_tables_do_not_contain_rank_column(self):
        """Waiting and Evaluations tables do not render the Rank column header."""
        app = Application.objects.create(
            job=self.job_sales_staff,
            first_name="Ada",
            last_name="Lovelace",
            email="ada@computing.org",
            phone="09197778899",
            ai_score=98,
            status="Shortlisted",
            interview_scheduled=False,
        )
        resp_waiting = self.client.get(f"{reverse('interviews')}?tab=waiting")
        self.assertEqual(resp_waiting.status_code, 200)
        self.assertNotContains(resp_waiting, '<th class="th-rank"')
        self.assertContains(resp_waiting, "Applications Waiting for Interview")

        from hr.models import Interview
        intv = Interview.objects.create(
            interview_type="HR Interview",
            interviewer="Admin User",
            date="2026-11-06",
            time="10:00:00",
            status="Scheduled",
        )
        intv.applicants.add(app)

        resp_eval = self.client.get(f"{reverse('interviews')}?tab=evaluations")
        self.assertEqual(resp_eval.status_code, 200)
        self.assertNotContains(resp_eval, '<th class="th-rank"')
        self.assertContains(resp_eval, "Candidate Interview Evaluations")

    def test_legacy_interview_detail_redirects_to_evaluations(self):
        """GET request to legacy /hr/interviews/<pk>/ redirects to evaluations tab."""
        from hr.models import Interview
        intv = Interview.objects.create(
            interview_type="HR Interview",
            interviewer="Admin User",
            date="2026-11-07",
            time="10:00:00",
            status="Scheduled",
        )
        url = reverse("interview_detail", kwargs={"pk": intv.pk})
        resp = self.client.get(url)
        self.assertRedirects(resp, f"{reverse('interviews')}?tab=evaluations")

    def test_schedules_tab_does_not_contain_session_details_or_legacy_update_buttons(self):
        """Schedules & Overview tab does not render Session Details or legacy Update buttons."""
        from hr.models import Interview
        app = Application.objects.create(
            job=self.job_sales_staff,
            first_name="Grace",
            last_name="Hopper",
            email="grace@navy.mil",
            phone="09196665544",
            ai_score=96,
            status="Interview",
            interview_scheduled=True,
        )
        overdue_intv = Interview.objects.create(
            interview_type="HR Interview",
            interviewer="Admin User",
            date="2020-01-01",
            time="10:00:00",
            status="Scheduled",
        )
        overdue_intv.applicants.add(app)

        from datetime import date, timedelta
        upcoming_date = date.today() + timedelta(days=2)
        upcoming_intv = Interview.objects.create(
            interview_type="HR Interview",
            interviewer="Admin User",
            date=upcoming_date,
            time="11:00:00",
            status="Scheduled",
        )
        upcoming_intv.applicants.add(app)

        resp = self.client.get(f"{reverse('interviews')}?tab=schedules")
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, "Session Details")
        self.assertNotContains(resp, "btn-resolve-status")
        self.assertContains(resp, "View Candidates")


class HRReportsAndFinalDecisionTests(TestCase):
    def setUp(self):
        invalidate_hr_cache()
        self.client = Client()
        self.staff_user = User.objects.create_user(
            username="hr_reviewer",
            password="testpassword123",
            first_name="Jane",
            last_name="Reviewer",
            is_staff=True
        )
        self.hr_group, _ = Group.objects.get_or_create(name="HR")
        self.staff_user.groups.add(self.hr_group)
        self.client.login(username="hr_reviewer", password="testpassword123")

        self.dept = "Engineering"
        self.job = Job.objects.create(
            title="Senior Backend Engineer",
            department=self.dept,
            job_type="FULL-TIME",
            status="Active"
        )
        self.applicant = Application.objects.create(
            job=self.job,
            first_name="Ada",
            last_name="Lovelace",
            email="ada@computing.org",
            phone="09171234567",
            ai_score=94,
            status="Interview",
            interview_scheduled=True,
        )

    def test_reports_subnav_and_stat_cards_ordering(self):
        """Top KPI stat cards appear before the sub-nav bar; 4 sub-nav tabs exist."""
        url = reverse("reports")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        content = response.content.decode("utf-8")
        stat_pos = content.find("reports-stat-cards-top")
        subnav_pos = content.find("reports-subnav-card")
        if subnav_pos == -1:
            subnav_pos = content.find("reports-subnav-container")
        self.assertTrue(stat_pos != -1, "reports-stat-cards-top not found")
        self.assertTrue(subnav_pos != -1, "reports-subnav-card/container not found")
        self.assertTrue(stat_pos < subnav_pos, "KPI stat cards must appear before sub-nav bar")

        self.assertContains(response, 'id="tab-btn-audit"')
        self.assertContains(response, 'id="tab-btn-cancelled"')
        self.assertContains(response, 'id="tab-btn-evaluations"')
        self.assertContains(response, 'id="tab-btn-final_decision"')
        self.assertContains(response, "Candidates with Final Decision")

    def test_reports_audit_logs_only_hr_actions(self):
        """Audit logs show HR user actions and exclude generic django admin logs."""
        from hr.models import AuditLog
        from hr.utils import purge_legacy_admin_logs, seed_applicant_management_logs_if_empty

        # Create a mock admin log that mentions django administrative action
        AuditLog.objects.create(
            user=self.staff_user,
            user_name="admin",
            action="OTHER",
            action_display="Admin Action",
            target_model="LogEntry",
            details="Administrative action on LogEntry #1",
        )
        # Create an authentic HR applicant management log
        AuditLog.objects.create(
            user=self.staff_user,
            user_name=self.staff_user.get_full_name(),
            action="INTERVIEW_SCHEDULED",
            action_display="Interview Scheduled",
            target_model="Application",
            target_id=str(self.applicant.pk),
            target_repr=f"{self.applicant.first_name} {self.applicant.last_name}",
            details="Technical interview scheduled.",
        )

        purge_legacy_admin_logs()
        url = f"{reverse('reports')}?tab=audit"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        # Confirm HR action is present
        self.assertContains(response, "Interview Scheduled")
        # Confirm admin action was purged
        self.assertNotContains(response, "Administrative action on")

    def test_evaluated_candidates_has_final_review_button(self):
        """Evaluated candidates tab replaces 'View Report' with 'Final Review' action button."""
        from hr.models import CandidateEvaluation
        CandidateEvaluation.objects.create(
            application=self.applicant,
            evaluator=self.staff_user,
            evaluator_name=self.staff_user.get_full_name(),
            technical_competence=5,
            communication_skills=4,
            problem_solving=5,
            cultural_fit=4,
            leadership_potential=4,
            recommendation="Strong Hire",
            status="Completed",
        )

        url = f"{reverse('reports')}?tab=evaluations"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        # Replaced button check
        self.assertContains(response, "Final Review")
        self.assertContains(response, f"openFinalReviewModal({self.applicant.pk})")
        self.assertNotContains(response, "View Report")

    def test_final_review_modal_endpoint(self):
        """AJAX endpoint loads applicant profile modal with rubric scores and decision form."""
        from hr.models import CandidateEvaluation
        CandidateEvaluation.objects.create(
            application=self.applicant,
            evaluator=self.staff_user,
            evaluator_name=self.staff_user.get_full_name(),
            technical_competence=5,
            communication_skills=4,
            problem_solving=5,
            cultural_fit=4,
            leadership_potential=4,
            recommendation="Strong Hire",
            strengths_notes="Exceptional algorithm design skills",
            weaknesses_notes="None noted",
            status="Completed",
        )

        url = reverse("final_review_modal", kwargs={"pk": self.applicant.pk})
        response = self.client.get(url, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(response.status_code, 200)

        self.assertContains(response, "Ada Lovelace")
        self.assertContains(response, "Senior Backend Engineer")
        self.assertContains(response, "Interview Evaluation Summary")
        self.assertContains(response, "Strong Hire")
        self.assertContains(response, "Exceptional algorithm design skills")
        self.assertContains(response, 'id="decision-hire"')
        self.assertContains(response, 'id="decision-not-hire"')
        self.assertContains(response, 'id="final_decision_notes_input"')
        self.assertContains(response, "Confirm Final Decision")

    def test_finalize_candidate_decision_hired(self):
        """Finalizing candidate as Hired updates evaluation, application status, and creates audit log."""
        from hr.models import CandidateEvaluation, AuditLog
        eval_obj = CandidateEvaluation.objects.create(
            application=self.applicant,
            evaluator=self.staff_user,
            status="Completed",
            recommendation="Strong Hire",
        )

        url = reverse("finalize_candidate_decision", kwargs={"pk": self.applicant.pk})
        post_data = {
            "decision": "Hired",
            "final_notes": "Candidate accepted starting package. Preparing contract.",
        }
        response = self.client.post(url, post_data)
        self.assertEqual(response.status_code, 302)
        self.assertIn("tab=final_decision", response.url)

        eval_obj.refresh_from_db()
        self.assertEqual(eval_obj.final_decision, "Hired")
        self.assertEqual(eval_obj.final_decision_notes, "Candidate accepted starting package. Preparing contract.")
        self.assertEqual(eval_obj.final_decision_by, self.staff_user)
        self.assertIsNotNone(eval_obj.final_decision_date)

        self.applicant.refresh_from_db()
        self.assertEqual(self.applicant.status, "Hired")

        audit_entry = AuditLog.objects.filter(
            action="FINAL_DECISION_HIRED",
            target_id=str(self.applicant.pk)
        ).first()
        self.assertIsNotNone(audit_entry)
        self.assertIn("Hired", audit_entry.details)

    def test_finalize_candidate_decision_not_hired_requires_notes(self):
        """Finalizing candidate as Not Hired requires a note; valid note updates status to Rejected."""
        from hr.models import CandidateEvaluation, AuditLog
        eval_obj = CandidateEvaluation.objects.create(
            application=self.applicant,
            evaluator=self.staff_user,
            status="Completed",
            recommendation="Hold",
        )

        url = reverse("finalize_candidate_decision", kwargs={"pk": self.applicant.pk})

        # Submit without notes
        response_invalid = self.client.post(url, {"decision": "Not Hired", "final_notes": ""})
        self.assertEqual(response_invalid.status_code, 302)
        eval_obj.refresh_from_db()
        self.assertIsNone(eval_obj.final_decision)

        # Submit with valid explanation note
        response_valid = self.client.post(url, {
            "decision": "Not Hired",
            "final_notes": "Candidate lacked necessary backend framework experience.",
        })
        self.assertEqual(response_valid.status_code, 302)

        eval_obj.refresh_from_db()
        self.assertEqual(eval_obj.final_decision, "Not Hired")
        self.assertEqual(eval_obj.final_decision_notes, "Candidate lacked necessary backend framework experience.")
        self.applicant.refresh_from_db()
        self.assertEqual(self.applicant.status, "Rejected")

        audit_entry = AuditLog.objects.filter(
            action="FINAL_DECISION_NOT_HIRED",
            target_id=str(self.applicant.pk)
        ).first()
        self.assertIsNotNone(audit_entry)
        self.assertIn("Not Hired", audit_entry.details)

    def test_candidates_with_final_decision_tab_department_structure(self):
        """Candidates with Final Decision tab separates Hired and Not Hired with department & job level layout."""
        from hr.models import CandidateEvaluation

        # Candidate 1: Hired
        CandidateEvaluation.objects.create(
            application=self.applicant,
            evaluator=self.staff_user,
            final_decision="Hired",
            final_decision_notes="Top performer",
            final_decision_by=self.staff_user,
            status="Completed",
        )
        self.applicant.status = "Hired"
        self.applicant.save()

        # Candidate 2: Not Hired
        app2 = Application.objects.create(
            job=self.job,
            first_name="Charles",
            last_name="Babbage",
            email="charles@difference.org",
            phone="09189998877",
            ai_score=78,
            status="Rejected",
        )
        CandidateEvaluation.objects.create(
            application=app2,
            evaluator=self.staff_user,
            final_decision="Not Hired",
            final_decision_notes="Failed technical assessment benchmark",
            final_decision_by=self.staff_user,
            status="Completed",
        )

        url = f"{reverse('reports')}?tab=final_decision"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        # Distinct sections
        self.assertContains(response, "Hired Candidates")
        self.assertContains(response, "Not Hired Candidates")
        self.assertContains(response, "Engineering Department")
        self.assertContains(response, "Senior Backend Engineer")
        self.assertContains(response, "Ada Lovelace")
        self.assertContains(response, "Charles Babbage")
        self.assertContains(response, "Failed technical assessment benchmark")

        # Department filter check
        dept_url = f"{reverse('reports')}?tab=final_decision&final_dept=Engineering"
        resp_dept = self.client.get(dept_url)
        self.assertEqual(resp_dept.status_code, 200)
        self.assertContains(resp_dept, "Engineering Department")

        # Search filter check
        search_url = f"{reverse('reports')}?tab=final_decision&final_search=Ada"
        resp_search = self.client.get(search_url)
        self.assertEqual(resp_search.status_code, 200)
        self.assertContains(resp_search, "Ada Lovelace")

    def test_candidate_profile_stage_five_and_final_review_modal(self):
        """Candidate detail page renders 5-stage stepper, Final Decision stage card, and modal container."""
        from hr.models import CandidateEvaluation
        CandidateEvaluation.objects.create(
            application=self.applicant,
            evaluator=self.staff_user,
            status="Completed",
            overall_rating=4.8,
            recommendation="Strong Hire",
        )

        url = reverse("candidate_detail", kwargs={"pk": self.applicant.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        # 5-stage progress stepper
        self.assertContains(response, "5. Final Decision")
        # Candidate Stage CTA card in hero Column 3
        self.assertContains(response, "Final Decision: Pending")
        # Next Actions in hero Column 4
        self.assertContains(response, "Conduct Final Review")
        # Stage 5 Box in profile body
        self.assertContains(response, "Stage 5: Final Hiring Determination")
        # Modal container and opener JS function
        self.assertContains(response, 'id="final-review-modal-container"')
        self.assertContains(response, "openFinalReviewModal")


class HRDashboardModernizationTests(TestCase):
    def setUp(self):
        invalidate_hr_cache()
        self.client = Client()
        self.hr_user = User.objects.create_user(
            username="admin",
            password="testpassword123",
            first_name="John",
            last_name="Smith",
            is_staff=True,
        )
        self.hr_group, _ = Group.objects.get_or_create(name="HR")
        self.hr_user.groups.add(self.hr_group)
        self.client.login(username="admin", password="testpassword123")

        self.dept = "Engineering"
        self.job = Job.objects.create(
            title="Senior AI Engineer",
            department=self.dept,
            job_type="FULL-TIME",
            status="Active"
        )
        self.app = Application.objects.create(
            job=self.job,
            first_name="Marie",
            last_name="Curie",
            email="marie@radioactivity.org",
            phone="09181112233",
            ai_score=95,
            status="Screening",
        )

    def test_dashboard_personalized_greeting(self):
        """Dashboard greets current HR user by actual name rather than username admin."""
        url = reverse("dashboard")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Welcome back, John Smith!")
        self.assertNotContains(response, "Welcome back, admin!")

    def test_dashboard_quick_actions_and_action_center_removed(self):
        """Action Center and Quick Actions sections are removed from the dashboard."""
        url = reverse("dashboard")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "<h3>Action Center</h3>")
        self.assertNotContains(response, "<h3>Quick Actions</h3>")

    def test_dashboard_visual_charts_in_context_and_dom(self):
        """Dashboard passes chart_data_json and renders canvas elements for Chart.js."""
        url = reverse("dashboard")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn("chart_data_json", response.context)
        self.assertContains(response, 'id="recruitmentTrendChart"')
        self.assertContains(response, 'id="departmentDoughnutChart"')
        self.assertContains(response, 'id="aiScoreChart"')
        self.assertContains(response, "chart.umd.min.js")

    def test_notification_bell_and_reactive_api(self):
        """Notification bell is dynamic and reactive via the notifications feed and mark-read API."""
        from hr.models import HRNotification

        # Initial seed check / unread notification creation
        HRNotification.objects.create(
            notification_type="NEW_APPLICATION",
            title="New Application: Marie Curie",
            message="Applied for Senior AI Engineer",
            is_read=False,
        )

        # GET API
        feed_url = reverse("hr_notifications_feed")
        feed_resp = self.client.get(feed_url, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(feed_resp.status_code, 200)
        data = feed_resp.json()
        self.assertEqual(data["status"], "success")
        self.assertGreater(data["unread_count"], 0)
        self.assertTrue(any("Marie Curie" in n["title"] for n in data["notifications"]))

        # Mark all as read POST API
        mark_url = reverse("mark_notification_read")
        mark_resp = self.client.post(mark_url, {}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(mark_resp.status_code, 200)
        mark_data = mark_resp.json()
        self.assertEqual(mark_data["status"], "success")
        self.assertEqual(mark_data["unread_count"], 0)

        # Confirm all are read in DB
        self.assertEqual(HRNotification.objects.filter(is_read=False).count(), 0)

    def test_reports_tabs_kpi_strip_placement(self):
        """Reports cancelled and evaluations tabs render sleek contextual KPI strips."""
        # Cancelled tab
        resp_cancelled = self.client.get(f"{reverse('reports')}?tab=cancelled")
        self.assertEqual(resp_cancelled.status_code, 200)
        self.assertContains(resp_cancelled, "reports-kpi-strip")
        self.assertContains(resp_cancelled, "Resume Screening Drop-Off")
        self.assertContains(resp_cancelled, "Post-Interview Disqualified")

        # Evaluations tab
        resp_eval = self.client.get(f"{reverse('reports')}?tab=evaluations")
        self.assertEqual(resp_eval.status_code, 200)
        self.assertContains(resp_eval, "reports-kpi-strip")
        self.assertContains(resp_eval, "Total Evaluated")
        self.assertContains(resp_eval, "Avg Rubric Score")

    def test_dashboard_does_not_contain_recent_applicants(self):
        """Recent Applicants has been moved out of Dashboard; verify dashboard bottom row."""
        resp = self.client.get(reverse("dashboard"))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, "<h3>Recent Applicants</h3>")
        self.assertContains(resp, "Candidate Pipeline")
        self.assertContains(resp, "AI Talent Quality Distribution")

    def test_candidates_subnav_tabs_rendered(self):
        """Candidates page renders sub-navigation tabs for All Applicants and Recent Applicants."""
        resp = self.client.get(reverse("candidates"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "candidates-subnav-container")
        self.assertContains(resp, "All Applicants")
        self.assertContains(resp, "Recent Applicants")
        self.assertContains(resp, 'id="tab-pane-all"')
        self.assertContains(resp, 'id="tab-pane-recent"')

    def test_candidates_recent_applicants_tab_content(self):
        """Recent Applicants tab renders latest submissions with candidate details and links."""
        resp = self.client.get(f"{reverse('candidates')}?tab=recent")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["active_tab"], "recent")
        self.assertIn("recent_applications", resp.context)
        self.assertGreater(len(resp.context["recent_applications"]), 0)

        # Check that latest applicant is displayed with role, department and review link
        latest_app = resp.context["recent_applications"][0]
        self.assertContains(resp, latest_app.first_name)
        self.assertContains(resp, latest_app.job.title)
        self.assertContains(resp, reverse("candidate_detail", args=[latest_app.id]))

    def test_minimized_no_additional_candidates_beyond_top_3(self):
        """When a job has 3 or fewer applicants, candidate table displays minimized empty state."""
        # Create a job with exactly 2 applicants
        small_job = Job.objects.create(
            title="Junior Graphic Designer",
            department="Marketing",
            job_type="FULL-TIME",
            status="Active"
        )
        for i in range(2):
            Application.objects.create(
                job=small_job,
                first_name=f"Designer{i+1}",
                last_name="Test",
                email=f"designer{i+1}@test.com",
                phone="09112223344",
                ai_score=85 - i,
                status="Screening",
            )

        url = reverse("candidate_job_table", args=[small_job.id])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

        # Verify the minimized empty state is rendered
        self.assertContains(resp, "empty-table-minimized")
        self.assertContains(resp, "All 2 applicants are displayed in the top candidate cards above")
        self.assertContains(resp, "No additional candidates beyond Top 3")
        # Verify the bulky empty-table-state is NOT rendered for non-search
        self.assertNotContains(resp, "empty-table-state")

    def test_search_empty_state_preserved(self):
        """When searching for a candidate with no match, detailed search empty state is rendered."""
        url = reverse("candidate_job_table", args=[self.job.id])
        resp = self.client.get(f"{url}?search=NonExistentApplicantName123")
        self.assertEqual(resp.status_code, 200)

        self.assertContains(resp, "empty-table-state")
        self.assertContains(resp, 'No candidates found matching "NonExistentApplicantName123"')
        self.assertNotContains(resp, "empty-table-minimized")


class HRUIEnhancementsTests(TestCase):
    """
    Tests for the UI enhancements across entire /hr/ app:
    1. Translucent hero section & reactive notification bell across all 5 navigation pages.
    2. New Department button relocation next to Filter by Department dropdown in Job Management.
    3. Contextual Print Report button in every sub-nav section of Reports.
    4. Categorized notifications (including HR Team actions).
    5. Removal of Origin column in Audit Trail table to maximize Details & Description space.
    """

    def setUp(self):
        invalidate_hr_cache()
        self.client = Client()
        self.hr_user = User.objects.create_user(
            username="hr_tester",
            password="testpassword123",
            first_name="Eleanor",
            last_name="Vance",
            is_staff=True,
        )
        self.hr_group, _ = Group.objects.get_or_create(name="HR")
        self.hr_user.groups.add(self.hr_group)
        self.client.login(username="hr_tester", password="testpassword123")

        self.dept = "Engineering"
        self.job = Job.objects.create(
            title="Full Stack Developer",
            department=self.dept,
            job_type="FULL-TIME",
            status="Active"
        )
        self.applicant = Application.objects.create(
            job=self.job,
            first_name="Alan",
            last_name="Turing",
            email="alan@enigma.org",
            phone="09189998877",
            ai_score=98,
            status="Interview",
            interview_scheduled=True,
        )

    def test_hero_section_and_notification_bell_in_all_5_navigation_pages(self):
        """Verify translucent hero section and notification bell are rendered on all 5 navigation pages."""
        pages = [
            ("dashboard", reverse("dashboard")),
            ("job_management", reverse("job_management")),
            ("candidates", reverse("candidates")),
            ("interviews", reverse("interviews")),
            ("reports", reverse("reports")),
        ]

        for page_name, url in pages:
            with self.subTest(page=page_name):
                resp = self.client.get(url)
                self.assertEqual(resp.status_code, 200)
                content = resp.content.decode("utf-8")
                self.assertIn("dashboard-hero-section", content, f"Hero section missing on {page_name}")
                self.assertIn("notif-bell-btn", content, f"Notification bell button missing on {page_name}")
                self.assertIn("notif-wrapper", content, f"Notification wrapper missing on {page_name}")
                self.assertIn("notif-dropdown", content, f"Notification dropdown missing on {page_name}")

    def test_job_management_new_department_relocation(self):
        """New Department button is moved next to Filter by Department dropdown in top toolbar."""
        resp = self.client.get(reverse("job_management"))
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode("utf-8")

        # Verify button exists and has correct id and toolbar class
        self.assertIn('id="open-new-department-modal"', content)
        self.assertIn("btn-new-dept-toolbar", content)
        # Verify it is positioned within the candidates-top-toolbar alongside deptSelect
        toolbar_pos = content.find("candidates-top-toolbar")
        dept_select_pos = content.find('id="deptSelect"')
        btn_new_dept_pos = content.find('id="open-new-department-modal"')
        self.assertTrue(toolbar_pos != -1)
        self.assertTrue(dept_select_pos > toolbar_pos)
        self.assertTrue(btn_new_dept_pos > dept_select_pos, "New Department button must follow department dropdown")

    def test_reports_print_buttons_in_every_subnav_section(self):
        """Reports header print button is removed; each sub-nav tab contains a contextual print button."""
        # Top reports page does not have header print button in header-actions
        resp = self.client.get(reverse("reports"))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'class="header-actions"')

        # Verify each of the 4 sub-nav tabs has a contextual print button
        subnav_tabs = ["audit", "cancelled", "evaluations", "final_decision"]
        for tab in subnav_tabs:
            with self.subTest(tab=tab):
                resp_tab = self.client.get(f"{reverse('reports')}?tab={tab}")
                self.assertEqual(resp_tab.status_code, 200)
                self.assertContains(resp_tab, "btn-print-subnav")
                self.assertContains(resp_tab, 'onclick="window.print()"')

    def test_audit_logs_origin_column_removed(self):
        """Origin (IP address) column is removed from Audit trail table to provide more space for Details."""
        from hr.models import AuditLog

        AuditLog.objects.create(
            user=self.hr_user,
            user_name="Eleanor Vance",
            action="JOB_CREATED",
            action_display="Job Created",
            target_model="Job",
            target_repr="Full Stack Developer",
            details="Comprehensive job posting created with all required skills.",
            ip_address="192.168.1.100",
        )

        resp = self.client.get(f"{reverse('reports')}?tab=audit")
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode("utf-8")

        # Verify header does NOT contain Origin
        self.assertNotIn("<th>Origin</th>", content)
        self.assertNotIn("Origin</th>", content)
        # Verify 192.168.1.100 is not rendered in the table cell
        self.assertNotIn("192.168.1.100", content)
        # Details & Description header and content are present
        self.assertIn("Details &amp; Description", content)
        self.assertIn("Comprehensive job posting created with all required skills.", content)

    def test_notifications_category_navigation_and_hr_team_actions(self):
        """Notification bell includes category tabs and HR Team action category."""
        from hr.models import HRNotification

        # Create an HR Team action notification
        HRNotification.objects.create(
            notification_type="HR_ACTION",
            title="Job Created: Full Stack Developer",
            message="Eleanor Vance created a new job posting.",
            link="/hr/reports/?tab=audit",
            is_read=False,
        )

        # Feed API returns category 'team'
        feed_url = reverse("hr_notifications_feed")
        resp = self.client.get(feed_url, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "success")

        team_notif = next((n for n in data["notifications"] if n["type"] == "HR_ACTION"), None)
        self.assertIsNotNone(team_notif)
        self.assertEqual(team_notif["category"], "team")

        # Check notification dropdown markup has category tabs
        dash_resp = self.client.get(reverse("dashboard"))
        self.assertEqual(dash_resp.status_code, 200)
        content = dash_resp.content.decode("utf-8")
        self.assertIn('data-category="all"', content)
        self.assertIn('data-category="applications"', content)
        self.assertIn('data-category="interviews"', content)
        self.assertIn('data-category="team"', content)
        self.assertIn('data-category="unread"', content)

    def test_hr_action_logged_creates_team_notification(self):
        """log_hr_action creates an AuditLog and an HRNotification for team-wide visibility."""
        from hr.models import HRNotification
        from hr.utils import log_hr_action
        from django.test import RequestFactory

        rf = RequestFactory()
        req = rf.post("/hr/jobs/create/")
        req.user = self.hr_user

        initial_count = HRNotification.objects.filter(notification_type="HR_ACTION").count()
        log_hr_action(
            req,
            action="JOB_CREATED",
            target_repr="Cybersecurity Specialist",
            details="Created new cybersecurity role.",
            target_model="Job",
        )

        final_count = HRNotification.objects.filter(notification_type="HR_ACTION").count()
        self.assertEqual(final_count, initial_count + 1)
        latest = HRNotification.objects.filter(notification_type="HR_ACTION").latest("created_at")
        self.assertIn("Cybersecurity Specialist", latest.title)













