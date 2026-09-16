from django.test import TestCase, RequestFactory
from django.contrib.auth.models import User
from django.core.cache import cache
from django.db import IntegrityError
from main.rate_limit import check_rate_limit, is_rate_limited
from main.turnstile import verify_turnstile
from jobs.models import Job, Application


class SecurityRateLimitTests(TestCase):
    def setUp(self):
        cache.clear()
        self.factory = RequestFactory()
        self.user = User.objects.create_user(
            username="securitytest@example.com",
            email="securitytest@example.com",
            password="Password123!"
        )

    def tearDown(self):
        cache.clear()

    def test_rate_limit_allows_3_and_blocks_4th_per_ip(self):
        """Verify that exactly 3 actions per hour are permitted per IP, and the 4th is blocked."""
        request = self.factory.post("/test-endpoint/", REMOTE_ADDR="198.51.100.1")

        # Attempts 1, 2, 3 (with debounce disabled for rate limit budget testing)
        for i in range(1, 4):
            is_limited, err = check_rate_limit(
                request,
                action_key="test_action",
                limit=3,
                window_seconds=3600,
                enable_debounce=False,
            )
            self.assertFalse(is_limited, f"Attempt {i} should be allowed.")
            self.assertEqual(err, "")

        # 4th attempt must be rejected
        is_limited, err = check_rate_limit(
            request,
            action_key="test_action",
            limit=3,
            window_seconds=3600,
            enable_debounce=False,
        )
        self.assertTrue(is_limited, "4th attempt must be blocked by rate limit.")
        self.assertIn("Rate limit exceeded", err)
        self.assertIn("3 times per hour", err)

    def test_rate_limit_per_account(self):
        """Verify rate limit applies per user account even if IP changes."""
        req1 = self.factory.post("/test-endpoint/", REMOTE_ADDR="198.51.100.10")
        req1.user = self.user

        for i in range(3):
            is_limited, _ = check_rate_limit(
                req1,
                action_key="account_action",
                limit=3,
                window_seconds=3600,
                account_identifier=self.user.email,
                enable_debounce=False,
            )
            self.assertFalse(is_limited)

        # 4th request from a DIFFERENT IP but SAME user must be blocked
        req2 = self.factory.post("/test-endpoint/", REMOTE_ADDR="198.51.100.20")
        req2.user = self.user

        is_limited, err = check_rate_limit(
            req2,
            action_key="account_action",
            limit=3,
            window_seconds=3600,
            account_identifier=self.user.email,
            enable_debounce=False,
        )
        self.assertTrue(is_limited, "Different IP with same user account must still be rate-limited.")
        self.assertIn("Rate limit exceeded", err)

    def test_rapid_fire_debounce_blocks_instant_burst(self):
        """Verify that rapid-fire requests within cooldown window are rejected."""
        request = self.factory.post("/test-endpoint/", REMOTE_ADDR="198.51.100.30")

        # First request succeeds
        is_limited, _ = check_rate_limit(
            request,
            action_key="burst_action",
            limit=3,
            window_seconds=3600,
            enable_debounce=True,
            debounce_seconds=3,
        )
        self.assertFalse(is_limited)

        # Second request immediately afterwards is blocked by debounce
        is_limited, err = check_rate_limit(
            request,
            action_key="burst_action",
            limit=3,
            window_seconds=3600,
            enable_debounce=True,
            debounce_seconds=3,
        )
        self.assertTrue(is_limited)
        self.assertIn("submitting too fast", err)

    def test_cloudflare_turnstile_verification(self):
        """Verify Turnstile verification catches empty token and handles valid test token."""
        # Empty token must fail
        valid, err = verify_turnstile("", remote_ip="127.0.0.1")
        self.assertFalse(valid)
        self.assertIn("Cloudflare security verification", err)

        # Cloudflare dummy test token passes
        valid, err = verify_turnstile("XXXX.DUMMY.TOKEN.XXXX", remote_ip="127.0.0.1")
        self.assertTrue(valid)
        self.assertEqual(err, "")

    def test_duplicate_job_application_prevention(self):
        """Verify that the same applicant cannot apply to the same job twice (unique constraint)."""
        job = Job.objects.create(
            title="Baker",
            department="Bakery",
            job_type="FULL-TIME",
            status="Active"
        )

        app1 = Application.objects.create(
            applicant=self.user,
            job=job,
            first_name="Jane",
            last_name="Doe",
            email="janedoe@example.com",
            phone="09123456789",
            status="Pending"
        )
        self.assertIsNotNone(app1.id)

        # Second submission for same user & job must raise IntegrityError at DB level
        with self.assertRaises(IntegrityError):
            Application.objects.create(
                applicant=self.user,
                job=job,
                first_name="Jane",
                last_name="Doe",
                email="janedoe@example.com",
                phone="09123456789",
                status="Pending"
            )
