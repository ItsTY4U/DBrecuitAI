
from django.shortcuts import render, redirect
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.models import User
from django.http import JsonResponse
from django.core.files.storage import default_storage
from django.utils import timezone
from jobs.recommendations import get_recommended_jobs
from .models import ApplicantProfile
from jobs.models import Application
from django.contrib import messages


from jobs.ai import extract_resume_text, parse_resume

from .forms import (
    ApplicantSignupForm,
    ApplicantLoginForm,
    ApplicantProfileForm,
    ApplicantUserForm
)

# Create your views here.
def signup(request):

    if request.user.is_authenticated:
        return redirect("jobs")

    form = ApplicantSignupForm()

    if request.method == "POST":

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

            login(request, user)

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
        }
    )
    
    
def applicant_login(request):
    if request.user.is_authenticated:
        return redirect("jobs")
    
    form = AuthenticationForm(
        request, 
        data=request.POST or None
    )
    
    if request.method == "POST":
        if form.is_valid():
            login(request, form.get_user())
            
            next_url = request.POST.get("next") or request.GET.get("next")
            
            if next_url:
                return redirect(next_url)
            return redirect("home")
        
    return render(request, "accounts/login.html",{"form": form, "next": request.GET.get("next", "")})

def applicant_logout(request):
    
    logout(request)
    
    return redirect("home")

def process_profile_resume(profile):
    
    if not profile.default_resume:
        return False
    
    try:
        resume_path = profile.default_resume.path
        
        resume_text = extract_resume_text(resume_path)
        
        parsed_data = parse_resume(resume_text)
        
        if not parsed_data:
            return False
        
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
        
        return True
    
    except Exception as e:
        print("Profile resume processing error:", e)
        
        profile.resume_processed = False
        
        profile.save(update_fields=["resume_processed"])
        
        return False

@login_required
def profile(request):

    profile, created = ApplicantProfile.objects.get_or_create(
        user=request.user
    )

    if request.method == "POST":

        user_form = ApplicantUserForm(
            request.POST,
            instance=request.user
        )

        profile_form = ApplicantProfileForm(
            request.POST,
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

            # Save user information
            user = user_form.save(commit=False)

            user.email = user_form.cleaned_data["email"]
            user.username = user.email

            user.save()

            # Save applicant profile
            profile = profile_form.save()

            # Process new resume
            if resume_changed:
                processed = process_profile_resume(profile)
                
                if processed:
                    messages.success(request,
                                    "Your resume was successfully processed. "
                                    "Job recommendations have been updated.")
                else:
                    messages.error(request,
                                    "Your resume was uploaded, but it could not be processed. "
                                    "Please Try Again.")
                    
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

    # Calculate recommendations AFTER profile is loaded/saved
    recommended_jobs = get_recommended_jobs(profile)
    
    applications = Application.objects.filter(
        applicant=request.user
    ).select_related("job").order_by("-created_at")

    return render(
        request,
        "accounts/profile.html",
        {
            "user_form": user_form,
            "profile_form": profile_form,
            "profile": profile,
            "recommended_jobs": recommended_jobs,
            "applications": applications,
        }
    )
    
def process_signup_resume(request):
    
    if request.method != "POST":
        return JsonResponse(
            {"error": "Invalid request."},
            status=400
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
        
    try:
        
        temp_path = default_storage.save(
            f"temp_resumes/{resume.name}",
            resume
        )
        
        full_path = default_storage.path(temp_path)
        
        # Extract resume text
        resume_text = extract_resume_text(full_path)
        
        # Parse resume with Gemini
        parsed_data = parse_resume(resume_text)
        
        # Delete temp file
        default_storage.delete(temp_path)
        
        if not parsed_data:
            return JsonResponse(
                {
                    "error": "Unable to process the resume."
                },
                status=400
            )
        # Save proceed resume data temp
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
                "error": "An error occured while processing the resume."
            },
            status=500
        )