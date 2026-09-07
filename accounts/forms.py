from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.forms import AuthenticationForm
import re

from .models import ApplicantProfile

class ApplicantSignupForm(forms.Form):

    email = forms.EmailField(
        widget=forms.EmailInput(attrs={
            "placeholder": "Enter your email address"
        })
    )

    first_name = forms.CharField(
        max_length=150,
        widget=forms.TextInput(attrs={
            "placeholder": "Enter your first name"
        })
    )

    middle_name = forms.CharField(
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={
            "placeholder": "Enter your middle name"
        })
    )

    last_name = forms.CharField(
        max_length=150,
        widget=forms.TextInput(attrs={
            "placeholder": "Enter your last name"
        })
    )
    
    default_resume = forms.FileField(
        required=False,
        widget=forms.ClearableFileInput(
            attrs={"accept": ".pdf"}
        )
    )

    password1 = forms.CharField(
        widget=forms.PasswordInput(attrs={
            "placeholder": "Enter your password"
        })
    )

    password2 = forms.CharField(
        widget=forms.PasswordInput(attrs={
            "placeholder": "Confirm your password"
        })
    )
    
    class Meta:
        model = User
        fields = [
            "first_name",
            "last_name",
            "email",
        ]
        widgets = {
            "first_name": forms.TextInput(
                attrs={
                    "placeholder": "First Name"
                }
            ),
            "last_name": forms.TextInput(
                attrs={
                    "placeholder": "Last Name"
                }
            ),
            "email": forms.TextInput(
                attrs={
                    "placeholder": "Email Address"
                }
            ),
        }
        
    def clean_password1(self):
        password1 = self.cleaned_data.get("password1")
        
        if len(password1) < 8:
            raise forms.ValidationError(
                "Password must be at least 8 characters."
            )
        
        if not re.search(r"[0-9]", password1):
            raise forms.ValidationError(
                "Password must contain at least one number."
            )
            
        if not re.search(r"[!@#$%&*_-]", password1):
            raise forms.ValidationError(
                "Password must contain at least one special characted (!@#$%&*_-)."
            )
        
        if not re.search(r"[A-Z]", password1):
            raise forms.ValidationError(
                "Password must contain at least one capiptal letter."
            )
            
        return password1
    
    def clean_email(self):
        email = self.cleaned_data["email"].lower().strip()
        
        if User.objects.filter(username=email).exists():
            raise forms.ValidationError(
                "An account with this email already exists."
            )
        return email
        
    def clean(self):
        cleaned_data = super().clean()
        
        password1 = cleaned_data.get("password1")
        password2 = cleaned_data.get("password2")
        
        if password1:
            if len(password1) < 8:
                self.add_error(
                    "password1",
                    "Password must be at least 8 characters long."
                )
            
            if not any(char.isupper() for char in password1):
                self.add_error(
                    "password1",
                    "Password must contain at least 1 Capital letter."
                )
                
            if not any(char.isdigit() for char in password1):
                self.add_error(
                    "password1",
                    "Password must contain at least 1 number."
                )
                
            if not any(char in "!@#$%&*_-" for char in password1):
                self.add_error(
                    "password1",
                    "Password must contain at least 1 special character"
                )
        
        if password1 and password2:
            if password1 != password2:
                raise forms.ValidationError(
                "Passwords do not match."
                )
        return cleaned_data
    
    def clean_default_resume(self):
        resume = self.cleaned_data.get("default_resume")
        
        if resume:
            
            if not resume.name.lower().endswith(".pdf"):
                raise forms.ValidationError(
                    "Only PDF files are allowed."
                )
                
            max_size = 5 * 1024 * 1024
            
            if resume.size > max_size:
                raise forms.ValidationError(
                    "Resume file must not exceed 5MB."
                )
                
        return resume
    
class ApplicantLoginForm(AuthenticationForm):
    
    username = forms.EmailField(
        label="Email Address",
        widget=forms.EmailInput(
            attrs={
                "placeholder": "Enter your Email",
                "autocomplete": "email",
            }
        )
    )
    
class ApplicantUserForm(forms.ModelForm):

    class Meta:
        model = User
        fields = [
            "first_name",
            "last_name",
            "email",
        ]

        widgets = {
            "first_name": forms.TextInput(
                attrs={
                    "placeholder": "First Name"
                }
            ),
            "last_name": forms.TextInput(
                attrs={
                    "placeholder": "Last Name"
                }
            ),
            "email": forms.EmailInput(
                attrs={
                    "placeholder": "Email Address"
                }
            ),
        }

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        current_email = (self.instance.email or "").strip().lower() if self.instance.pk else ""

        if email == current_email:
            return email  # keeping your own email is always fine

        if User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email
        

class ApplicantProfileForm(forms.ModelForm):
    
    class Meta:
        model = ApplicantProfile
        fields = [
            "phone",
            "address",
            "default_resume",
        ]
        
        widgets = {
            "phone": forms.TextInput(
                attrs={
                    "placeholder": "Phone Number"
                }
            ),
            "address": forms.Textarea(
                attrs={
                    "placeholder": "Address",
                    "rows": 3
                }
            ),
        }

    def clean_default_resume(self):
        resume = self.cleaned_data.get("default_resume")
        if resume and hasattr(resume, "name") and not isinstance(resume, str):
            if not resume.name.lower().endswith(".pdf"):
                raise forms.ValidationError("Only PDF files are allowed.")
            if hasattr(resume, "size") and resume.size > 5 * 1024 * 1024:
                raise forms.ValidationError("Resume file must not exceed 5MB.")
        return resume