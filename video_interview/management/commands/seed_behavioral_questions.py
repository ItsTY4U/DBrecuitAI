from django.core.management.base import BaseCommand
from jobs.models import Job
from video_interview.models import BehavioralQuestion

SAMPLE_QUESTIONS = [
    # General / Adaptability
    {
        "text": "Tell us about a time you encountered a significant setback or unexpected change on a project. How did you adapt your approach?",
        "category": "Adaptability",
    },
    {
        "text": "Describe a situation where you had to learn a completely new tool, system, or skill under a tight deadline.",
        "category": "Adaptability",
    },
    # Problem Solving
    {
        "text": "Can you share an example of a complex problem you resolved by analyzing data or finding root causes?",
        "category": "Problem Solving",
    },
    {
        "text": "Walk us through a time when you identified an inefficiency in a daily procedure and took initiative to streamline it.",
        "category": "Problem Solving",
    },
    # Teamwork & Collaboration
    {
        "text": "Describe a scenario where you disagreed with a colleague or supervisor regarding a work decision. How did you handle the discussion?",
        "category": "Teamwork",
    },
    {
        "text": "Tell us about a time you went above and beyond to support a struggling team member to achieve a collective milestone.",
        "category": "Teamwork",
    },
    # Customer Service & Communication
    {
        "text": "Describe an experience dealing with an unhappy or demanding customer/stakeholder. How did you turn the situation around?",
        "category": "Customer Focus",
    },
    # Integrity & Accountability
    {
        "text": "Tell us about a time when you made an error that impacted others. How did you take ownership and rectify it?",
        "category": "Accountability",
    },
]


class Command(BaseCommand):
    help = "Seeds default behavioral interview questions for jobs and global pool."

    def handle(self, *args, **options):
        count = 0
        # Seed global questions
        for item in SAMPLE_QUESTIONS:
            obj, created = BehavioralQuestion.objects.get_or_create(
                job=None,
                question_text=item["text"],
                defaults={
                    "category": item["category"],
                    "is_active": True,
                }
            )
            if created:
                count += 1

        # Also seed per-job questions if jobs exist
        jobs = Job.objects.all()
        for job in jobs:
            for item in SAMPLE_QUESTIONS[:4]:
                obj, created = BehavioralQuestion.objects.get_or_create(
                    job=job,
                    question_text=f"[{job.title}] {item['text']}",
                    defaults={
                        "category": item["category"],
                        "is_active": True,
                    }
                )
                if created:
                    count += 1

        self.stdout.write(self.style.SUCCESS(f"Successfully seeded {count} behavioral interview questions."))
