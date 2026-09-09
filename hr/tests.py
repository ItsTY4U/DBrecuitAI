from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User, Group
from jobs.models import Job, Application

class CandidateManagementTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.staff_user = User.objects.create_user(
            username="admin_hr",
            password="testpassword123",
            is_staff=True
        )
        hr_group, _ = Group.objects.get_or_create(name="HR")
        self.staff_user.groups.add(hr_group)
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
        # /admin/jobs/ must have both button and modal
        res_jobs = self.client.get(reverse("job_management"))
        self.assertEqual(res_jobs.status_code, 200)
        self.assertContains(res_jobs, 'id="open-post-modal"')
        self.assertContains(res_jobs, 'id="post-job-modal"')

        # /admin/ (dashboard) must NOT have button or modal
        res_dash = self.client.get(reverse("dashboard"))
        self.assertEqual(res_dash.status_code, 200)
        self.assertNotContains(res_dash, 'id="open-post-modal"')
        self.assertNotContains(res_dash, 'id="post-job-modal"')

        # /admin/candidates/ must NOT have button or modal
        res_cand = self.client.get(reverse("candidates"))
        self.assertEqual(res_cand.status_code, 200)
        self.assertNotContains(res_cand, 'id="open-post-modal"')
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



