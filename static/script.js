document.addEventListener("DOMContentLoaded", function () {
  const issueForm = document.getElementById("issueForm");
  const issuesList = document.getElementById("issuesList");

  // Load issues from MongoDB
  async function loadIssues() {
    const response = await fetch("/issues/");
    const issues = await response.json();
    issuesList.innerHTML = "";

    issues.forEach((issue) => {
      const li = document.createElement("li");
      li.innerHTML = `<strong>${issue.title}</strong>: ${issue.description} <br> Location: ${issue.location} | Status: ${issue.status}`;
      issuesList.appendChild(li);
    });
  }

  // Handle form submission (only if form exists)
  if (issueForm) {
    issueForm.addEventListener("submit", async function (event) {
      event.preventDefault();
      const title = document.getElementById("title").value;
      const description = document.getElementById("description").value;
      const location = document.getElementById("location").value;

      const response = await fetch("/report/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title,
          description,
          location,
          status: "Submitted",
        }),
      });

      if (response.ok) {
        alert("Issue reported successfully!");
        issueForm.reset();
        loadIssues(); // Reload issues after adding a new one
      } else {
        alert("Failed to report issue.");
      }
    });
  }

  // Load issues only if the issues list exists
  if (issuesList) {
    loadIssues();
  }
});
