document.addEventListener("DOMContentLoaded", function () {
  const token = Cookies.get("access_token"); // Get the token from cookies
  const loginBtn = document.getElementById("login-btn");
  const logoutForm = document.getElementById("logout-form");

  // Toggle visibility based on the presence of the access token
  if (token) {
    // If token exists, show logout form and hide login button
    loginBtn?.classList.add("hidden"); // Hide login button
    logoutForm?.classList.remove("hidden"); // Show logout form
  } else {
    // If token does not exist, hide logout form and show login button
    logoutForm?.classList.add("hidden"); // Hide logout form
    loginBtn?.classList.remove("hidden"); // Show login button
  }
});

document.addEventListener("DOMContentLoaded", function () {
  const issueForm = document.getElementById("issueForm");
  const useMyLocationBtn = document.getElementById("useMyLocation");
  const locationInput = document.getElementById("location");

  const defaultLat = 40.8099;
  const defaultLng = 44.4878;

  const map = L.map("osm-map", {
    center: [defaultLat, defaultLng],
    zoom: 14,
  });

  L.tileLayer("https://{s}.tile.osm.org/{z}/{x}/{y}.png", {
    attribution:
      '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  }).addTo(map);

  let marker = L.marker([defaultLat, defaultLng], { draggable: true }).addTo(
    map
  );
  locationInput.value = `Lat: ${defaultLat}, Lng: ${defaultLng}`;

  marker.on("dragend", function (event) {
    const position = marker.getLatLng();
    locationInput.value = `Lat: ${position.lat}, Lng: ${position.lng}`;
  });

  map.on("click", function (e) {
    const lat = e.latlng.lat;
    const lng = e.latlng.lng;

    marker.setLatLng([lat, lng]);

    locationInput.value = `Lat: ${lat}, Lng: ${lng}`;
  });

  useMyLocationBtn.addEventListener("click", function () {
    if (navigator.geolocation) {
      navigator.geolocation.getCurrentPosition(
        function (position) {
          const lat = position.coords.latitude;
          const lng = position.coords.longitude;

          map.setView([lat, lng], 14);
          marker.setLatLng([lat, lng]);

          locationInput.value = `Lat: ${lat}, Lng: ${lng}`;
        },
        function () {
          alert(
            "Unable to retrieve your location. Please allow location access."
          );
        }
      );
    } else {
      alert("Geolocation is not supported by your browser.");
    }
  });

  issueForm.addEventListener("submit", async function (event) {
    event.preventDefault();
    const formData = new FormData(issueForm);
    const response = await fetch("/report/", {
      method: "POST",
      body: formData,
    });
    if (response.ok) {
      alert("Issue reported successfully!");
      issueForm.reset();

      map.setView([defaultLat, defaultLng], 14);
      marker.setLatLng([defaultLat, defaultLng]);
      locationInput.value = `Lat: ${defaultLat}, Lng: ${defaultLng}`;
    } else {
      alert("Failed to report issue.");
    }
  });
});
