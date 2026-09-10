document.addEventListener("DOMContentLoaded", () => {

    const themeToggle = document.getElementById("themeToggle");

    if (!themeToggle) return;

    // Check if the user previously selected a theme
    const savedTheme = localStorage.getItem("unicamplink-theme");

    // Default theme = dark mode
    if (savedTheme === "light") {
        document.body.classList.add("light-mode");
        updateThemeButton(true);
    } else {
        document.body.classList.remove("light-mode");
        updateThemeButton(false);
    }

    // Theme button
    themeToggle.addEventListener("click", () => {

        const isLightMode =
            document.body.classList.toggle("light-mode");

        // Save the user's choice
        localStorage.setItem(
            "unicamplink-theme",
            isLightMode ? "light" : "dark"
        );

        updateThemeButton(isLightMode);
    });

    // Change button text
    function updateThemeButton(isLightMode) {

        if (isLightMode) {

            themeToggle.innerHTML = "🌙 Dark Mode";

            themeToggle.setAttribute(
                "aria-label",
                "Switch to dark mode"
            );

        } else {

            themeToggle.innerHTML = "☀️ Light Mode";

            themeToggle.setAttribute(
                "aria-label",
                "Switch to light mode"
            );
        }
    }

});