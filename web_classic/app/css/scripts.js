// Función para mostrar la sección correcta
function showSection(id) {
    const sections = document.querySelectorAll("section");
    sections.forEach(s => s.classList.remove("active"));
    const target = document.getElementById(id);
    if (target) target.classList.add("active");
}

// Autoexpandible menú lateral
document.querySelectorAll('.menu-title').forEach(title => {
    title.addEventListener('click', () => {
        const submenu = title.nextElementSibling;
        if (submenu) {
            submenu.style.display = submenu.style.display === 'block' ? 'none' : 'block';
        }
    });
});

// Por defecto mostramos la primera sección
showSection('news');
