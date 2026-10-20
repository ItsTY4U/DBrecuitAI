from django.db import migrations, models

def add_vacancies_column(apps, schema_editor):
    connection = schema_editor.connection
    with connection.cursor() as cursor:
        table_name = "jobs_job"
        if connection.vendor == "sqlite":
            cursor.execute(f"PRAGMA table_info({table_name})")
            columns = [row[1] for row in cursor.fetchall()]
            if "vacancies" not in columns:
                cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN vacancies integer DEFAULT 1 NOT NULL")
        elif connection.vendor == "postgresql":
            cursor.execute("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns 
                        WHERE table_name='jobs_job' AND column_name='vacancies'
                    ) THEN
                        ALTER TABLE jobs_job ADD COLUMN vacancies integer DEFAULT 1 NOT NULL;
                    END IF;
                END $$;
            """)
        else:
            try:
                cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN vacancies integer DEFAULT 1 NOT NULL")
            except Exception:
                pass

def remove_vacancies_column(apps, schema_editor):
    pass

class Migration(migrations.Migration):

    dependencies = [
        ("jobs", "0034_alter_application_status"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name="job",
                    name="vacancies",
                    field=models.PositiveIntegerField(
                        default=1,
                        help_text="Number of open positions available for this job.",
                        verbose_name="Number of Vacancies",
                    ),
                ),
            ],
            database_operations=[
                migrations.RunPython(add_vacancies_column, reverse_code=remove_vacancies_column),
            ],
        )
    ]
