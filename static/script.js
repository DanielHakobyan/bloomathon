document.addEventListener("DOMContentLoaded", function () {
  const issueForm = document.getElementById("issueForm");
  const issuesList = document.getElementById("issuesList");

  // Function to load issues
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

  // Handle form submission (only on report_issue.html)
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
      } else {
        alert("Failed to report issue.");
      }
    });
  }

  // Load issues only on view_issues.html
  if (issuesList) {
    loadIssues();
  }
});
