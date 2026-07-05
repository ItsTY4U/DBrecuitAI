const dropZone = document.getElementById("drop-zone");
const fileInput = document.getElementById("resume-upload");

const uploadIdle = document.querySelector(".upload-idle");
const uploadLoading = document.querySelector(".upload-loading");

const step1 = document.getElementById("step-1");
const step2 = document.getElementById("step-2");


dropZone.addEventListener("click", () => {
    fileInput.click()
});

dropZone.addEventListener("dragover", (e) => {
    e.preventDefault();
});

dropZone.addEventListener("drop", (e) => {
    e.preventDefault();
    fileInput.files = e.dataTransfer.files;
});

fileInput.addEventListener("change", () => {
    if (fileInput.isDefaultNamespace.length > 0) {
        console.log(fileInput.files[0].name);
    }
});

fileInput.addEventListener("change", function() {
    console.log(this.files);
    alert("Selected: " + this.files[0].name);
});

fileInput.addEventListener("change", () => {
    if (fileInput.files.length === 0) return;

    uploadIdle.classList.add("hidden");
    uploadLoading.classList.add("hidden");

    setTimeout(() => {
        step1.classList.add("hidden");
        step2.classList.remove("hidden");
    }, 2000);
});

fileInput.addEventListener("change", () => {
    if (fileInput.files.length > 0) {
        fileInput.form.requestSubmit();
    }
});

document.addEventListener("DOMContentLoaded", function () {

    const modal = document.getElementById('post-job-modal');
    const openBtn = document.getElementById('open-post-modal');
    const closeBtn = document.getElementById('close-post-modal');
    const cancelBtn = document.getElementById('cancel-modal');

    openBtn.addEventListener('click', () => {
        modal.classList.add('active');
    });

    function closeModal() {
        modal.classList.remove('active');
    }

    closeBtn.addEventListener('click', closeModal);
    cancelBtn.addEventListener('click', closeModal);

});