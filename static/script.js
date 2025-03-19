document.addEventListener("DOMContentLoaded", function () {
  const issueForm = document.getElementById("issueForm");

  // Handle form submission (only on report_issue.html)
  if (issueForm) {
    issueForm.addEventListener("submit", async function (event) {
      event.preventDefault();
      const formData = new FormData(issueForm); // Use FormData for file uploads

      const response = await fetch("/report/", {
        method: "POST",
        body: formData, // Send FormData as body for multipart form submission
      });

      if (response.ok) {
        alert("Issue reported successfully!");
        issueForm.reset();
      } else {
        alert("Failed to report issue.");
      }
    });
  }
});
