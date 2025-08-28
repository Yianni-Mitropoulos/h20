let currentPage = 1;
let pages = [];
const userInputs = {};
const pageOriginalHTML = {};
let pageEntryHandlers = [];

document.addEventListener("DOMContentLoaded", () => {
    pages = Array.from(document.querySelectorAll('.page'));
    pages.forEach((page, idx) => {
        pageOriginalHTML[idx] = page.innerHTML;
    });

    // Auto-generate pageEntryHandlers based on input fields in previous pages
    pageEntryHandlers = pages.map((page, pageIndex) => {
        const handlers = {};
        const inputs = page.querySelectorAll('input, textarea, select');
        
        // For each page, generate handlers for future pages (not the current page)
        pages.slice(0, pageIndex).forEach((previousPage, prevIndex) => {
            const previousInputs = previousPage.querySelectorAll('input, textarea, select');
            previousInputs.forEach(input => {
                if (input.id) {
                    // Add a handler for each input on previous pages
                    handlers[input.id] = () => userInputs[input.id];
                }
            });
        });

        // Return the handlers for this page
        return handlers;
    });

    showPage(1, true);
});

function saveCurrentInput() {
    const page = pages[currentPage - 1];
    if (!page) return;
    const input = page.querySelector('input, textarea, select');
    if (input) {
        // Save the input value based on its ID
        userInputs[input.id] = input.value;
    }
}

function restoreInputForPage(pageNum) {
    const page = pages[pageNum - 1];
    if (!page) return;
    const input = page.querySelector('input, textarea, select');
    if (input && userInputs[input.id] !== undefined) {
        input.value = userInputs[input.id];
    }
}

function interpolateTextOnPage(substitutionMap, pageNum = currentPage) {
    const pageIdx = pageNum - 1;
    const page = pages[pageIdx];
    
    // Restore original HTML for the page
    page.innerHTML = pageOriginalHTML[pageIdx];
    
    // Loop through all substitutions in the map and replace them in the HTML
    let html = page.innerHTML;
    for (let key in substitutionMap) {
        let val = substitutionMap[key] ? substitutionMap[key]() : '';
        html = html.split(key).join(val);
    }
    page.innerHTML = html;
}

function next() {
    saveCurrentInput();
    currentPage++;
    interpolateTextOnPage(pageEntryHandlers[currentPage - 1]);
    showPage(currentPage, true);
    restoreInputForPage(currentPage);
}

function prev() {
    saveCurrentInput();
    currentPage--;
    interpolateTextOnPage(pageEntryHandlers[currentPage - 1]);
    showPage(currentPage, true);
    restoreInputForPage(currentPage);
}

function showPage(pageNumber, skipInterp) {
    pages.forEach(page => page.classList.remove('active-page'));
    const page = pages[pageNumber - 1];
    page.classList.add('active-page');
    if (!skipInterp) {
        interpolateTextOnPage(pageEntryHandlers[pageNumber - 1], pageNumber);
    }
    restoreInputForPage(pageNumber);
}

function copyToClipboard() {
    const scriptText = document.querySelector('.active-page .bash-script-box pre').innerText;
    navigator.clipboard.writeText(scriptText).then(() => {
        alert('Script copied to clipboard!');
    });
}

function finishWorkflow() {
    alert("Workflow Complete!");
}