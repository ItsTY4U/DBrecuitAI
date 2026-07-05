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

document.addEventListener("DOMContentLoaded", () => {

    const container = document.getElementById("requirements-container");
    const addBtn = document.getElementById("add-requirement");

    if (!container || !addBtn) return;

    addBtn.addEventListener("click", () => {

        const row = document.createElement("div");
        row.className = "requirement-row";
        row.style.marginTop = "10px";

        row.innerHTML = `
            <input
                type="text"
                name="requirements"
                placeholder="Enter a requirement"
                required>

            <button
                type="button"
                class="remove-requirement">
                ×
            </button>
        `;

        container.appendChild(row);
    });

    container.addEventListener("click", function(e){

        if(e.target.classList.contains("remove-requirement")){

            e.target.parentElement.remove();

        }

    });

});