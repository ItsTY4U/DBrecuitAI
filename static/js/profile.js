document.addEventListener("DOMContentLoaded", function () {

    const editButton = document.getElementById("edit-profile-btn");
    const cancelButton = document.getElementById("cancel-profile-btn");
    const profileEdit = document.getElementById("profile-edit");

    console.log("profile.js loaded");
    console.log("Edit button:", editButton);
    console.log("Profile edit:", profileEdit);

    if (editButton && profileEdit) {

        editButton.addEventListener("click", function () {

            console.log("Edit button clicked");

            const isHidden =
                window.getComputedStyle(profileEdit).display === "none";

            if (isHidden) {

                profileEdit.style.display = "block";
                editButton.textContent = "Cancel";

                profileEdit.scrollIntoView({
                    behavior: "smooth",
                    block: "start"
                });

            } else {

                profileEdit.style.display = "none";
                editButton.textContent = "Edit profile";

            }

        });

    }

    if (cancelButton && profileEdit) {

        cancelButton.addEventListener("click", function () {

            profileEdit.style.display = "none";

            if (editButton) {
                editButton.textContent = "Edit profile";
            }

        });

    }

});