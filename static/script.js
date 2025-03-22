document.addEventListener("DOMContentLoaded", function () {
  const issueForm = document.getElementById("issueForm");
  const useMyLocationBtn = document.getElementById("useMyLocation");
  const locationInput = document.getElementById("location");

  // Default coordinates (Vanadzor, Armenia)
  const defaultLat = 40.8099;
  const defaultLng = 44.4878;

  // Initialize the Leaflet map in the "osm-map" div.
  const map = L.map("osm-map", {
    center: [defaultLat, defaultLng],
    zoom: 14,
  });

  // Add OpenStreetMap tile layer (using HTTPS)
  L.tileLayer("https://{s}.tile.osm.org/{z}/{x}/{y}.png", {
    attribution:
      '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  }).addTo(map);

  // Place a marker at the default location.
  let marker = L.marker([defaultLat, defaultLng]).addTo(map);
  locationInput.value = `Lat: ${defaultLat}, Lng: ${defaultLng}`;

  // Update the map with user's current location (on clicking "Use My Location" button)
  useMyLocationBtn.addEventListener("click", function () {
    if (navigator.geolocation) {
      navigator.geolocation.getCurrentPosition(
        function (position) {
          const lat = position.coords.latitude;
          const lng = position.coords.longitude;
          const newCenter = [lat, lng];
          map.setView(newCenter, 14);
          if (marker) {
            marker.remove(); // Remove the old marker
          }
          marker = L.marker(newCenter).addTo(map); // Add a new marker at the user's location
          locationInput.value = `Lat: ${lat}, Lng: ${lng}`;
        },
        function (error) {
          alert(
            "Unable to retrieve your location. Please allow location access."
          );
        }
      );
    } else {
      alert("Geolocation is not supported by your browser.");
    }
  });

  // Handle clicking on the map to manually set the location.
  map.on("click", function (e) {
    const lat = e.latlng.lat;
    const lng = e.latlng.lng;

    // Remove the old marker
    if (marker) {
      marker.remove();
    }

    // Add a new marker at the clicked position
    marker = L.marker([lat, lng]).addTo(map);

    // Update the input field with the selected coordinates
    locationInput.value = `Lat: ${lat}, Lng: ${lng}`;
  });

  // Handle form submission.
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
      // Reset map to default.
      map.setView([defaultLat, defaultLng], 14);
      if (marker) {
        marker.remove();
      }
      marker = L.marker([defaultLat, defaultLng]).addTo(map);
      locationInput.value = `Lat: ${defaultLat}, Lng: ${defaultLng}`;
    } else {
      alert("Failed to report issue.");
    }
  });
});
