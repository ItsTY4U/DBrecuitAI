document.addEventListener("DOMContentLoaded", function () {
    const dropZone = document.getElementById("drop-zone");
    const resumeInput = document.getElementById("resume-upload");
    const resumeForm = document.getElementById("resume-form");

    if (dropZone && resumeInput) {
        dropZone.addEventListener("click", function () {
            resumeInput.click();
        });

        resumeInput.addEventListener("change", function () {
            if (resumeInput.files.length > 0) {
                const file = resumeInput.files[0];
                console.log("Selected file:", file.name);

                const idleEl = document.querySelector(".upload-idle");
                const loadingEl = document.querySelector(".upload-loading");
                if (idleEl) idleEl.classList.add("hidden");
                if (loadingEl) loadingEl.classList.remove("hidden");

                if (resumeForm && window.htmx) {
                    htmx.trigger(resumeForm, "submit");
                }
            }
        });
    }
});