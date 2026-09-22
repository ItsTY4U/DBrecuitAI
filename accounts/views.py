
from django.shortcuts import render, redirect
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.models import User
from django.http import JsonResponse
from django.core.files.storage import default_storage
from django.utils import timezone
from jobs.recommendations import get_recommended_jobs, get_applicant_strongest_field
from .models import ApplicantProfile
from jobs.models import Application
from django.contrib import messages
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner
from django.core.cache import cache


from jobs.ai import extract_resume_text, parse_resume

from django.conf import settings
from main.rate_limit import check_rate_limit, get_client_ip
from main.turnstile import verify_turnstile

from .forms import (
    ApplicantSignupForm,
    ApplicantLoginForm,
    ApplicantProfileForm,
    ApplicantUserForm,
    ApplicantAuthenticationForm,
)

# Create your views here.
def signup(request):

    if request.user.is_authenticated:
        return redirect("home")

    form = ApplicantSignupForm()
    turnstile_site_key = "" if getattr(settings, "DEBUG", False) else getattr(settings, "CLOUDFLARE_TURNSTILE_SITE_KEY", "")

    if request.method == "POST":
        # 1. Rate limiting & spam prevention (strictly 3 per hour per IP and per email, with debounce)
        email_candidate = request.POST.get("email", "").strip().lower()
        is_limited, limit_err = check_rate_limit(
            request,
            action_key="signup",
            limit=3,
            window_seconds=3600,
            account_identifier=email_candidate,
            enable_debounce=True,
            debounce_seconds=3,
        )
        if is_limited:
            messages.error(request, limit_err)
            return render(
                request,
                "accounts/signup.html",
                {
                    "form": form,
                    "next": request.GET.get("next", ""),
                    "turnstile_site_key": turnstile_site_key,
                },
                status=429,
            )

        # 2. Cloudflare Turnstile verification for applicant signup
        turnstile_token = request.POST.get("cf-turnstile-response", "")
        turnstile_valid, turnstile_err = verify_turnstile(
            turnstile_token,
            remote_ip=get_client_ip(request),
        )
        if not turnstile_valid:
            messages.error(request, turnstile_err)
            form = ApplicantSignupForm(request.POST, request.FILES)
            return render(
                request,
                "accounts/signup.html",
                {
                    "form": form,
                    "next": request.GET.get("next", ""),
                    "turnstile_site_key": turnstile_site_key,
                },
            )

        form = ApplicantSignupForm(
            request.POST,
            request.FILES
        )

        if form.is_valid():

            email = form.cleaned_data["email"].lower().strip()
            
            # Get processed resume data
            resume_text = request.session.get(
                "signup_resume_text",
                ""
            )
            
            resume_data = request.session.get(
                "signup_resume_data",
                {}
            )

            # Create the user
            user = User.objects.create_user(
                username=email,
                email=email,
                first_name=form.cleaned_data["first_name"],
                last_name=form.cleaned_data["last_name"],
                password=form.cleaned_data["password1"],
            )

            # Create the applicant profile
            profile = ApplicantProfile.objects.create(
                user=user,
                middle_name=form.cleaned_data["middle_name"],
                default_resume=form.cleaned_data.get("default_resume"),

                resume_text=resume_text,
                resume_data=resume_data,

                resume_processed=bool(resume_data),
                resume_processed_at=timezone.now() if resume_data else None
            )

            # Remove temp resume data
            request.session.pop(
                "signup_resume_text",
                None
            )
            
            request.session.pop(
                "signup_resume_data",
                None
            )

            login(request, user, backend="django.contrib.auth.backends.ModelBackend")

            next_url = request.POST.get("next")

            if next_url:
                return redirect(next_url)

            return redirect("home")

    return render(
        request,
        "accounts/signup.html",
        {
            "form": form,
            "next": request.GET.get("next", ""),
            "turnstile_site_key": turnstile_site_key,
        }
    )
    
    
def applicant_login(request):
    if request.user.is_authenticated:
        if request.user.is_superuser:
            return redirect("/admin/")
        if request.user.groups.filter(name="HR").exists():
            return redirect("dashboard")
        return redirect("home")
    
    turnstile_site_key = "" if getattr(settings, "DEBUG", False) else getattr(settings, "CLOUDFLARE_TURNSTILE_SITE_KEY", "")

    form = ApplicantAuthenticationForm(
        request, 
        data=request.POST or None
    )
    
    if request.method == "POST":
        # Cloudflare Turnstile verification for applicant login
        turnstile_token = request.POST.get("cf-turnstile-response", "")
        turnstile_valid, turnstile_err = verify_turnstile(
            turnstile_token,
            remote_ip=get_client_ip(request),
        )
        if not turnstile_valid:
            messages.error(request, turnstile_err)
            return render(
                request,
                "accounts/login.html",
                {"form": form, "next": request.GET.get("next", ""), "turnstile_site_key": turnstile_site_key},
            )

        if form.is_valid():
            login(request, form.get_user())
            
            next_url = request.POST.get("next") or request.GET.get("next")
            
            if next_url and not next_url.startswith("/superadmin"):
                return redirect(next_url)
            return redirect("home")
        
    return render(request, "accounts/login.html", {"form": form, "next": request.GET.get("next", ""), "turnstile_site_key": turnstile_site_key})

def applicant_logout(request):
    
    logout(request)
    
    return redirect("home")

def process_profile_resume(profile):
    
    if not profile.default_resume:
        return False, "No resume file was uploaded."
    
    try:
        resume_text = extract_resume_text(profile.default_resume)
        
        if not resume_text or len(resume_text.strip()) < 30:
            return False, "Unable to extract readable text from your resume. Please ensure the PDF contains text and is not a scanned photo or image."

        parsed_data = parse_resume(resume_text)
        
        if not parsed_data:
            return False, "Unable to process resume data. Please try again."
        
        profile.resume_text = resume_text
        profile.resume_data = parsed_data
        profile.resume_processed = True
        profile.resume_processed_at = timezone.now()
        
        profile.save(
            update_fields=[
                "resume_text",
                "resume_data",
                "resume_processed",
                "resume_processed_at",
            ]
        )
        
        return True, ""
    
    except Exception as e:
        import logging
        logging.getLogger(__name__).error("Profile resume processing error: %s", e)
        
        profile.resume_processed = False
        profile.save(update_fields=["resume_processed"])
        
        return False, f"An unexpected error occurred while processing your resume: {str(e)}"


@login_required
def profile(request):

    profile, created = ApplicantProfile.objects.get_or_create(
        user=request.user
    )

    if request.method == "POST":
        # Rate limiting: 3 profile updates per hour per IP & account with debounce
        is_limited, limit_err = check_rate_limit(
            request,
            action_key="profile_update",
            limit=3,
            window_seconds=3600,
            account_identifier=request.user.email,
            enable_debounce=True,
            debounce_seconds=3,
        )
        if is_limited:
            messages.error(request, limit_err)
            return redirect("profile")

        # If resume file is also uploaded, check resume upload rate limit
        if request.FILES.get("default_resume"):
            is_resume_limited, resume_limit_err = check_rate_limit(
                request,
                action_key="upload_resume",
                limit=3,
                window_seconds=3600,
                account_identifier=request.user.email,
                enable_debounce=True,
                debounce_seconds=3,
            )
            if is_resume_limited:
                messages.error(request, resume_limit_err)
                return redirect("profile")

        post_data = request.POST.copy()
        if not post_data.get("email"):
            post_data["email"] = request.user.email
        if "first_name" not in post_data:
            post_data["first_name"] = request.user.first_name
        if "last_name" not in post_data:
            post_data["last_name"] = request.user.last_name
        if "phone" not in post_data:
            post_data["phone"] = profile.phone or ""
        if "address" not in post_data:
            post_data["address"] = profile.address or ""

        user_form = ApplicantUserForm(
            post_data,
            instance=request.user
        )

        profile_form = ApplicantProfileForm(
            post_data,
            request.FILES,
            instance=profile
        )

        if user_form.is_valid() and profile_form.is_valid():
            
            storage = messages.get_messages(request)
            
            for message in storage:
                pass

            resume_changed = bool(
                request.FILES.get("default_resume")
            )

            # Save user information (allow editing first_name, last_name, but keep sign-in email immutable)
            user = user_form.save(commit=False)
            user.first_name = user_form.cleaned_data.get("first_name", user.first_name)
            user.last_name = user_form.cleaned_data.get("last_name", user.last_name)
            user.email = request.user.email
            user.username = request.user.username
            user.save()

            # Save applicant profile
            profile = profile_form.save()

            # Process new resume
            if resume_changed:
                processed, err_msg = process_profile_resume(profile)
                
                if processed:
                    messages.success(request,
                                    "Your resume was successfully processed. "
                                    "Job recommendations have been updated.")
                else:
                    messages.error(request,
                                    err_msg or ("Your resume was uploaded, but it could not be processed. "
                                    "Please Try Again."))
                    
            else:
                messages.success(request, 
                                "Your profile has been updated successfully.")

            # Prevent form resubmission
            return redirect("profile")

    else:

        user_form = ApplicantUserForm(
            instance=request.user
        )

        profile_form = ApplicantProfileForm(
            instance=profile
        )

    applications = (
        Application.objects.filter(applicant=request.user)
        .select_related("job", "video_interview")
        .defer("ai_summary", "ai_strengths", "ai_weaknesses")
        .order_by("-created_at")
    )

    return render(
        request,
        "accounts/profile.html",
        {
            "user_form": user_form,
            "profile_form": profile_form,
            "profile": profile,
            "applications": applications,
        }
    )

@login_required
def profile_recommendations(request):
    """
    HTMX lazy-loaded endpoint to calculate and render job recommendations
    asynchronously so initial profile page load is instantaneous.
    """
    profile, _ = ApplicantProfile.objects.get_or_create(
        user=request.user
    )
    recommended_jobs = get_recommended_jobs(profile, limit=6)
    strongest_field_key, strongest_field_display = get_applicant_strongest_field(profile)
    return render(
        request,
        "accounts/partials/recommended_jobs.html",
        {
            "profile": profile,
            "recommended_jobs": recommended_jobs,
            "strongest_field": strongest_field_key,
            "strongest_field_display": strongest_field_display,
        }
    )
    
def process_signup_resume(request):
    if request.method != "POST":
        return JsonResponse(
            {"error": "Invalid request."},
            status=400
        )

    # Rate limiting: 3 per hour per IP & session with debounce
    is_limited, limit_err = check_rate_limit(
        request,
        action_key="upload_resume",
        limit=3,
        window_seconds=3600,
        account_identifier=request.session.session_key,
        enable_debounce=True,
        debounce_seconds=3,
    )
    if is_limited:
        return JsonResponse(
            {"error": limit_err},
            status=429
        )

    resume = request.FILES.get("resume")
    
    if not resume:
        return JsonResponse(
            {"error": "Please upload a resume."},
            status=400
        )
        
    if not resume.name.lower().endswith(".pdf"):
        return JsonResponse(
            {"error": "Only PDF files are allowed."},
            status=400
        )

    if resume.size > 5 * 1024 * 1024:
        return JsonResponse(
            {"error": "Resume file must not exceed 5MB."},
            status=400
        )
        
    try:
        # Extract resume text directly from uploaded file
        resume_text = extract_resume_text(resume)
        
        if not resume_text or not resume_text.strip():
            return JsonResponse(
                {
                    "error": "Unable to extract text from the resume. Please ensure the PDF contains readable text (not a scanned image)."
                },
                status=400
            )
        
        # Parse resume with Gemini
        parsed_data = parse_resume(resume_text)
        
        if not parsed_data:
            return JsonResponse(
                {
                    "error": "Unable to process the resume."
                },
                status=400
            )
        # Save processed resume data to session
        request.session["signup_resume_text"] = resume_text
        request.session["signup_resume_data"] = parsed_data
        
        return JsonResponse(
            {
                "success": True,
                "data": parsed_data
            }
        )
    except Exception as e:
        
        print("Signup resume processing error:", e)
        
        return JsonResponse(
            {
                "error": "An error occurred while processing the resume."
            },
            status=500
        )


def forgot_password(request):
    if request.method == "POST":
        email = request.POST.get("email", "").strip().lower()
        is_limited, limit_err = check_rate_limit(
            request,
            action_key="forgot_password",
            limit=3,
            window_seconds=3600,
            account_identifier=email,
            enable_debounce=True,
            debounce_seconds=3,
        )
        if is_limited:
            messages.error(request, limit_err)
            return render(request, "accounts/forgot_password.html", status=429)

    return render(request, "accounts/forgot_password.html")

def verify_password_otp(request):
    if request.method == "POST":
        is_limited, limit_err = check_rate_limit(
            request,
            action_key="verify_otp",
            limit=3,
            window_seconds=3600,
            enable_debounce=True,
            debounce_seconds=3,
        )
        if is_limited:
            messages.error(request, limit_err)
            return render(request, "accounts/verify_otp.html", status=429)

    return render(request, "accounts/verify_otp.html")


def google_verify_sent(request):
    """
    Renders confirmation that a verification link was sent to the applicant's Gmail.
    """
    if request.user.is_authenticated:
        return redirect("profile")

    email = request.session.get("pending_google_email", "")
    dev_verify_url = request.session.get("pending_google_dev_verify_url", "")

    return render(
        request,
        "accounts/google_verify_sent.html",
        {
            "email": email,
            "dev_verify_url": dev_verify_url,
        },
    )


def google_verify_approve(request, token):
    """
    Validates the secure approval link sent to the applicant's Gmail.
    On successful verification, completes authentication and redirects to profile.
    """
    if request.user.is_authenticated:
        return redirect("profile")

    signer = TimestampSigner(salt="google-auth-verify")
    try:
        # Link expires in 15 minutes (900 seconds)
        raw_token = signer.unsign(token, max_age=900)
        user_id_str, email, nonce = raw_token.split(":", 2)
    except SignatureExpired:
        messages.error(request, "Your verification link has expired (15-minute limit). Please sign in with Google again.")
        return redirect("applicant_login")
    except (BadSignature, ValueError):
        messages.error(request, "The verification link is invalid. Please sign in with Google again.")
        return redirect("applicant_login")

    # Replay protection: ensure single-use nonce is still in cache
    cache_key = f"google_auth_nonce_{user_id_str}_{nonce}"
    if not cache.get(cache_key):
        messages.error(
            request,
            "This approval link has already been used or has expired. Please sign in with Google again.",
        )
        return redirect("applicant_login")

    # Consume the token immediately
    cache.delete(cache_key)

    try:
        user = User.objects.get(pk=int(user_id_str))
    except (User.DoesNotExist, ValueError):
        messages.error(request, "User account not found. Please try signing in again.")
        return redirect("applicant_login")

    if not user.is_active:
        messages.error(request, "Your account is disabled. Please contact DBRecruitAI support.")
        return redirect("applicant_login")

    # Ensure profile exists
    ApplicantProfile.objects.get_or_create(user=user)

    # Clean up pending verification session data
    request.session.pop("pending_google_email", None)
    request.session.pop("pending_google_user_id", None)
    request.session.pop("pending_google_name", None)
    request.session.pop("pending_google_dev_verify_url", None)

    # Complete the login
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    messages.success(
        request,
        f"Google verification successful! Welcome back, {user.first_name or user.username}."
    )
    return redirect("profile")


def resend_google_verify(request):
    """
    Allows the applicant to request a new verification link if the previous one expired or was missed.
    Rate limited to 3 per 15 minutes.
    """
    if request.method != "POST":
        return redirect("google_verify_sent")

    user_id = request.session.get("pending_google_user_id")
    email = request.session.get("pending_google_email", "")

    if not user_id or not email:
        messages.info(request, "Your session has expired. Please sign in with Google again.")
        return redirect("applicant_login")

    # Rate limiting: 3 per 15 minutes per IP & email
    is_limited, limit_err = check_rate_limit(
        request,
        action_key="resend_google_verify",
        limit=3,
        window_seconds=900,
        account_identifier=email,
        enable_debounce=True,
        debounce_seconds=5,
    )
    if is_limited:
        messages.error(request, limit_err)
        return redirect("google_verify_sent")

    try:
        user = User.objects.get(pk=user_id)
    except User.DoesNotExist:
        messages.error(request, "User account not found. Please try signing in again.")
        return redirect("applicant_login")

    from .adapters import create_google_verification_token, send_google_verification_email

    token = create_google_verification_token(user, email)
    result, verify_url = send_google_verification_email(request, user, email, token)

    if not result.get("success") and getattr(settings, "DEBUG", False):
        request.session["pending_google_dev_verify_url"] = verify_url

    messages.success(request, f"A new verification link has been sent to {email}.")
    return redirect("google_verify_sent")