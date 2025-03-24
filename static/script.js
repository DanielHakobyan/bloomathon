document.addEventListener("DOMContentLoaded", function () {
  const issueForm = document.getElementById("issueForm");
  const useMyLocationBtn = document.getElementById("useMyLocation");
  const locationInput = document.getElementById("location");

  // Default coordinates (Vanadzor, Armenia)
  const defaultLat = 40.8099;
  const defaultLng = 44.4878;

  // Initialize the Leaflet map
  const map = L.map("osm-map", {
    center: [defaultLat, defaultLng],
    zoom: 14,
  });

  // Add OpenStreetMap tile layer
  L.tileLayer("https://{s}.tile.osm.org/{z}/{x}/{y}.png", {
    attribution:
      '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  }).addTo(map);

  // Create a marker at the default location and make it draggable
  let marker = L.marker([defaultLat, defaultLng], { draggable: true }).addTo(
    map
  );
  locationInput.value = `Lat: ${defaultLat}, Lng: ${defaultLng}`;

  // Update input when marker is moved manually
  marker.on("dragend", function (event) {
    const position = marker.getLatLng();
    locationInput.value = `Lat: ${position.lat}, Lng: ${position.lng}`;
  });

  // Handle map clicks to move the marker
  map.on("click", function (e) {
    const lat = e.latlng.lat;
    const lng = e.latlng.lng;

    // Move marker to clicked position
    marker.setLatLng([lat, lng]);

    // Update input field
    locationInput.value = `Lat: ${lat}, Lng: ${lng}`;
  });

  // Use "Use My Location" button
  useMyLocationBtn.addEventListener("click", function () {
    if (navigator.geolocation) {
      navigator.geolocation.getCurrentPosition(
        function (position) {
          const lat = position.coords.latitude;
          const lng = position.coords.longitude;

          // Move map and marker to current location
          map.setView([lat, lng], 14);
          marker.setLatLng([lat, lng]);

          // Update input field
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

  // Handle form submission
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

      // Reset map
      map.setView([defaultLat, defaultLng], 14);
      marker.setLatLng([defaultLat, defaultLng]);
      locationInput.value = `Lat: ${defaultLat}, Lng: ${defaultLng}`;
    } else {
      alert("Failed to report issue.");
    }
  });
});
