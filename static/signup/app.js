document.getElementById("signup-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const errorEl = document.getElementById("signup-error");
  errorEl.textContent = "";

  const body = {
    clinic_name: document.getElementById("clinic-name").value.trim(),
    admin_name: document.getElementById("admin-name").value.trim(),
    admin_contact: document.getElementById("admin-contact").value.trim(),
    admin_password: document.getElementById("admin-password").value,
  };

  try {
    const response = await fetch("/staff/signup", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error ? data.error.message : "Signup failed.");
    }

    // Same sessionStorage keys the dashboard reads -- so we hand off already signed in.
    sessionStorage.setItem("qf_token", data.access_token);
    sessionStorage.setItem("qf_role", data.role);
    sessionStorage.setItem("qf_clinic_id", data.clinic_id);

    document.getElementById("signup-screen").classList.add("hidden");
    document.getElementById("success-screen").classList.remove("hidden");
    document.getElementById("clinic-id-value").textContent = data.clinic_id;
    document.getElementById("patient-link-value").textContent =
      `${window.location.origin}/patient-app/?clinic=${data.clinic_id}`;

    setTimeout(() => { window.location.href = "/dashboard/"; }, 2500);
  } catch (err) {
    errorEl.textContent = err.message;
  }
});
