/**
 * Global utility functions for the application
 */

// Modal Enter key handling
document.addEventListener('DOMContentLoaded', () => {
    // Configureer alle modals voor Enter-toets ondersteuning
    setupAllModals();
});

/**
 * Koppelt de Enter-toets aan de primaire (meestal blauwe) knop in modals
 */
function setupAllModals() {
    // Verzamel alle modals in de applicatie
    const modals = document.querySelectorAll('div[id$="Modal"]');
    
    modals.forEach(modal => {
        const modalId = modal.id;
        
        // Zoek de primaire knop in deze modal (meestal de blauwe button)
        // We kijken eerst naar een .btn-primary of bg-blue klasse, dan naar een knop met een blauwe achtergrond
        // of als fallback de laatste knop in de footer (meestal de bevestigingsknop)
        const modalButtons = modal.querySelectorAll('button');
        let primaryButton = null;
        
        // Zoek eerst een knop met primary of blue class
        for (const button of modalButtons) {
            if (button.classList.contains('btn-primary') || 
                button.classList.contains('bg-blue-600') || 
                button.classList.contains('bg-blue-700')) {
                primaryButton = button;
                break;
            }
        }
        
        // Als fallback, neem de laatste knop in de footer als primaire knop
        if (!primaryButton && modalButtons.length > 0) {
            // Check voor knoppen in de footer area (meestal onderaan)
            const footerButtons = modal.querySelectorAll('.px-6.py-4.bg-gray-50 button');
            if (footerButtons.length > 0) {
                primaryButton = footerButtons[footerButtons.length - 1];
            } else {
                // Als laatste optie, neem gewoon de laatste knop
                primaryButton = modalButtons[modalButtons.length - 1];
            }
        }
        
        if (primaryButton) {
            // Stel de enter-toets in voor deze modal
            setupModalEnterKey(modal, primaryButton);
        }
    });
}

/**
 * Koppelt de Enter-toets aan een specifieke knop in een modal
 */
function setupModalEnterKey(modal, primaryButton) {
    if (!modal || !primaryButton) return;
    
    // Verwijder eerst eventuele bestaande handlers
    if (modal._keydownHandler) {
        modal.removeEventListener('keydown', modal._keydownHandler);
    }
    
    // Maak en sla de handler op zodat deze later kan worden verwijderd
    modal._keydownHandler = function(e) {
        if (e.key === 'Enter' && !e.ctrlKey && !e.shiftKey && !e.altKey && !e.metaKey) {
            // Voorkom dat de Enter-toets in textarea's de form submit trigger
            if (e.target.tagName.toLowerCase() === 'textarea') return;
            
            // Voorkom standaard form submit gedrag
            e.preventDefault();
            
            // Trigger klik op de primaire knop
            primaryButton.click();
        }
    };
    
    // Voeg event listener toe
    modal.addEventListener('keydown', modal._keydownHandler);
} 