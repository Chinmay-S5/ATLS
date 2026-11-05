/**
 * Main Dynamic AJAX Form Handlers & UI Controller
 * Provides asynchronous API interaction, live status messaging, modal management,
 * and responsive table updates for ATM (Port 5001) and Bank Portal (Port 5002).
 */

/**
 * Display a temporary floating toast notification in the UI.
 * @param {string} message - Notification text.
 * @param {'success'|'error'|'info'|'warning'} type - Semantic notification category.
 */
function showToast(message, type = 'info') {
    let container = document.getElementById('toast-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toast-container';
        container.className = 'fixed bottom-4 right-4 z-50 flex flex-col gap-2 max-w-sm';
        document.body.appendChild(container);
    }

    const toast = document.createElement('div');
    const isLightTheme = document.body.classList.contains('bank-light-theme') || document.body.classList.contains('atm-kiosk-theme');
    const colorClasses = isLightTheme ? {
        success: 'border-emerald-200 bg-emerald-50 text-emerald-700 shadow-md',
        error: 'border-rose-200 bg-rose-50 text-rose-700 shadow-md',
        warning: 'border-amber-200 bg-amber-50 text-amber-800 shadow-md',
        info: 'border-indigo-200 bg-indigo-50 text-indigo-700 shadow-md'
    }[type] || 'border-slate-200 bg-white text-slate-800 shadow-md' : {
        success: 'border-emerald-500/50 bg-[#10b981]/10 text-emerald-400',
        error: 'border-rose-500/50 bg-[#f43f5e]/10 text-rose-400',
        warning: 'border-amber-500/50 bg-[#f59e0b]/10 text-amber-400',
        info: 'border-blue-500/50 bg-[#2563eb]/10 text-blue-400'
    }[type] || 'border-zinc-700 bg-zinc-900 text-zinc-300';

    toast.className = `border px-4 py-3 rounded-xl text-xs font-mono shadow-lg transition-all duration-300 flex items-center justify-between gap-3 ${colorClasses}`;
    toast.innerHTML = `
        <span>${message}</span>
        <button onclick="this.parentElement.remove()" class="opacity-60 hover:opacity-100 font-bold">&times;</button>
    `;

    container.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = '0';
        setTimeout(() => toast.remove(), 300);
    }, 4500);
}

/**
 * Helper to execute standard JSON fetch requests with consistent error handling.
 * @param {string} url - API endpoint.
 * @param {object} options - Fetch options.
 * @returns {Promise<object>} Parsed JSON response.
 */
async function fetchAPI(url, options = {}) {
    try {
        const response = await fetch(url, {
            headers: {
                'Content-Type': 'application/json',
                ...options.headers
            },
            ...options
        });
        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.error || data.message || `Request failed with status ${response.status}`);
        }
        return data;
    } catch (err) {
        showToast(err.message, 'error');
        throw err;
    }
}

/**
 * Fast Cash button handler: Fills amount into the withdrawal input.
 * @param {number} amount - Amount in rupees.
 */
function setWithdrawAmount(amount) {
    const input = document.getElementById('withdraw-amount');
    if (input) {
        input.value = amount;
    }
}

/**
 * Quick fill card number and PIN on the ATM login screen for demonstration.
 * @param {string} cardNumber - 16-digit card number.
 * @param {string} pin - 4-digit PIN.
 */
function fillDemoCard(cardNumber, pin = '1234') {
    const cardInput = document.getElementById('card-input') || document.getElementById('card_number');
    const pinInput = document.getElementById('pin-input') || document.getElementById('pin');
    if (cardInput) cardInput.value = cardNumber;
    if (pinInput) pinInput.value = pin;
}

/**
 * Switch active ATM terminal transaction view (menu, withdraw, deposit, balance)
 * @param {'menu'|'withdraw'|'deposit'|'balance'} view - Selected panel ID.
 */
function showAtmOption(view) {
    const menu = document.getElementById('atm-menu-options');
    const withdrawView = document.getElementById('view-withdraw');
    const depositView = document.getElementById('view-deposit');
    const balanceView = document.getElementById('view-balance');

    if (!menu) return;

    // Hide all panels
    menu.classList.add('hidden');
    if (withdrawView) withdrawView.classList.add('hidden');
    if (depositView) depositView.classList.add('hidden');
    if (balanceView) balanceView.classList.add('hidden');

    if (view === 'withdraw' && withdrawView) {
        withdrawView.classList.remove('hidden');
        const input = document.getElementById('withdraw-amount');
        if (input) input.focus();
    } else if (view === 'deposit' && depositView) {
        depositView.classList.remove('hidden');
        const input = document.getElementById('deposit-amount');
        if (input) input.focus();
    } else if (view === 'balance' && balanceView) {
        balanceView.classList.remove('hidden');
    } else {
        menu.classList.remove('hidden');
    }
}

/**
 * Fast deposit button handler: fills amount into the deposit input.
 * @param {number} amount - Amount in rupees.
 */
function setDepositAmount(amount) {
    const input = document.getElementById('deposit-amount');
    if (input) {
        input.value = amount;
    }
}

/**
 * Toggle modal visibility by element ID.
 * @param {string} modalId - Target modal DOM element ID.
 * @param {boolean} show - Explicit show or hide boolean.
 */
function toggleModal(modalId, show = true) {
    const modal = document.getElementById(modalId);
    if (modal) {
        if (show) {
            modal.classList.remove('hidden');
            modal.classList.add('flex');
        } else {
            modal.classList.add('hidden');
            modal.classList.remove('flex');
        }
    }
}

// ============================================================================
// BANK PORTAL: CUSTOMER COMBOBOX & QUICK REGISTRATION CONTROLLERS
// ============================================================================

/** In-memory customer directory loaded from server template */
let bankCustomers = [];

/**
 * Initialize searchable customer combobox in New Account modal.
 * Handles instant filtering, item selection, keyboard/click dismiss,
 * and pre-selection.
 */
function initCustomerCombobox() {
    const custDataEl = document.getElementById('initial-customers-data');
    const searchInput = document.getElementById('customer-search-input');
    const menu = document.getElementById('customer-dropdown-menu');
    const hiddenId = document.getElementById('account-customer-id');
    const arrow = document.getElementById('customer-dropdown-arrow');
    const toggleBtn = document.getElementById('customer-dropdown-toggle');
    const wrapper = document.getElementById('customer-combobox-wrapper');
    const accountForm = document.querySelector('#new-account-modal form');

    if (!searchInput || !menu || !hiddenId) return;

    if (custDataEl) {
        try {
            bankCustomers = JSON.parse(custDataEl.textContent || '[]');
        } catch (err) {
            console.error('Failed to parse initial customers JSON:', err);
            bankCustomers = [];
        }
    }

    /**
     * Render dropdown list items based on filter query.
     * @param {string} filterText - Search query string.
     */
    function renderOptions(filterText = '') {
        const query = filterText.toLowerCase().trim();
        const matches = bankCustomers.filter(c => {
            const name = `${c.firstname || ''} ${c.lastname || ''}`.toLowerCase();
            const id = String(c.customer_id || '');
            const email = (c.email || '').toLowerCase();
            const phone = (c.phone_number || '').toLowerCase();
            return !query || name.includes(query) || id.includes(query) || email.includes(query) || phone.includes(query);
        });

        menu.innerHTML = '';
        if (matches.length === 0) {
            const empty = document.createElement('div');
            empty.className = 'px-3 py-3 text-slate-400 text-center text-[11px]';
            empty.textContent = `No customers found matching "${filterText}".`;
            menu.appendChild(empty);
            return;
        }

        matches.forEach(c => {
            const row = document.createElement('div');
            row.className = 'px-3 py-2 hover:bg-slate-100 cursor-pointer flex items-center justify-between transition-colors';
            const fullName = `${c.firstname} ${c.lastname || ''}`.trim();
            row.innerHTML = `
                <div class="truncate mr-2">
                    <span class="font-semibold text-slate-900">#${c.customer_id} ${fullName}</span>
                    <div class="text-[10px] text-slate-500 truncate">${c.email}${c.phone_number ? ' • ' + c.phone_number : ''}</div>
                </div>
                <span class="text-[10px] text-indigo-600 font-mono whitespace-nowrap">Select &rarr;</span>
            `;
            row.addEventListener('click', () => {
                selectCustomer(c);
                closeDropdown();
            });
            menu.appendChild(row);
        });
    }

    /**
     * Open dropdown menu and rotate indicator arrow.
     */
    function openDropdown() {
        menu.classList.remove('hidden');
        if (arrow) arrow.style.transform = 'rotate(180deg)';
    }

    /**
     * Close dropdown menu and reset indicator arrow.
     */
    function closeDropdown() {
        menu.classList.add('hidden');
        if (arrow) arrow.style.transform = 'rotate(0deg)';
    }

    /**
     * Toggle dropdown open / closed state.
     */
    function toggleDropdown() {
        if (menu.classList.contains('hidden')) {
            renderOptions(searchInput.value);
            openDropdown();
        } else {
            closeDropdown();
        }
    }

    // Toggle button handler
    if (toggleBtn) {
        toggleBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            toggleDropdown();
        });
    }

    // Input handlers
    searchInput.addEventListener('focus', () => {
        renderOptions(searchInput.value);
        openDropdown();
    });

    searchInput.addEventListener('input', (e) => {
        const val = e.target.value.toLowerCase().trim();
        // Check for exact match by full name, ID, or full display string
        const exactMatch = bankCustomers.find(c => {
            const fullName = `${c.firstname || ''} ${c.lastname || ''}`.toLowerCase().trim();
            const formatted = `#${c.customer_id} ${fullName} (${(c.email || '').toLowerCase()})`;
            return fullName === val || formatted.toLowerCase() === val || String(c.customer_id) === val;
        });
        if (exactMatch) {
            selectCustomer(exactMatch);
        }
        renderOptions(e.target.value);
        openDropdown();
    });

    // Enter key selects first filtered customer without submitting form
    searchInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            const query = searchInput.value.toLowerCase().trim();
            const matches = bankCustomers.filter(c => {
                const name = `${c.firstname || ''} ${c.lastname || ''}`.toLowerCase();
                const id = String(c.customer_id || '');
                const email = (c.email || '').toLowerCase();
                const phone = (c.phone_number || '').toLowerCase();
                return !query || name.includes(query) || id.includes(query) || email.includes(query) || phone.includes(query);
            });
            if (matches.length > 0) {
                selectCustomer(matches[0]);
                closeDropdown();
            }
        }
    });

    // On blur, synchronize display text with active selected customer
    searchInput.addEventListener('blur', () => {
        setTimeout(() => {
            if (hiddenId.value) {
                const current = bankCustomers.find(c => String(c.customer_id) === String(hiddenId.value));
                if (current) {
                    const fullName = `${current.firstname} ${current.lastname || ''}`.trim();
                    searchInput.value = `#${current.customer_id} ${fullName} (${current.email})`;
                }
            }
        }, 200);
    });

    // Close when clicking outside combobox wrapper
    document.addEventListener('click', (e) => {
        if (wrapper && !wrapper.contains(e.target)) {
            closeDropdown();
        }
    });

    // Validate customer selection on account form submit
    if (accountForm) {
        accountForm.addEventListener('submit', (e) => {
            if (!hiddenId.value) {
                e.preventDefault();
                const label = document.getElementById('customer-selection-label');
                if (label) {
                    label.innerHTML = '<span class="text-rose-400 font-bold">! Please search and select a customer from the dropdown.</span>';
                }
                searchInput.focus();
                showToast('Please select a customer before creating the account.', 'warning');
            }
        });
    }

    // Auto-select first customer if available
    if (bankCustomers.length > 0 && !hiddenId.value) {
        selectCustomer(bankCustomers[0]);
    }
}

/**
 * Select a customer programmatically, updating inputs and DOM labels.
 * @param {object} customer - Customer object with customer_id, firstname, lastname, email, phone_number.
 */
function selectCustomer(customer) {
    const searchInput = document.getElementById('customer-search-input');
    const hiddenId = document.getElementById('account-customer-id');
    const label = document.getElementById('customer-selection-label');
    const menu = document.getElementById('customer-dropdown-menu');
    const arrow = document.getElementById('customer-dropdown-arrow');

    if (!customer) return;

    const fullName = `${customer.firstname} ${customer.lastname || ''}`.trim();

    if (hiddenId) hiddenId.value = customer.customer_id;
    if (searchInput) searchInput.value = `#${customer.customer_id} ${fullName} (${customer.email})`;
    if (label) {
        label.innerHTML = `<span class="text-emerald-400 font-medium">✓ Selected: #${customer.customer_id} ${fullName}</span>`;
    }
    if (menu) menu.classList.add('hidden');
    if (arrow) arrow.style.transform = 'rotate(0deg)';
}

/**
 * Open the New Customer registration modal.
 */
function openNewCustomerModal() {
    const modal = document.getElementById('new-customer-modal');
    const form = document.getElementById('new-customer-form');
    const errBox = document.getElementById('new-customer-error');
    if (errBox) {
        errBox.classList.add('hidden');
        errBox.textContent = '';
    }
    if (form) {
        form.reset();
        // Set a reasonable default date
        const dobInput = document.getElementById('cust-dob');
        if (dobInput && !dobInput.value) {
            dobInput.value = '1995-01-01';
        }
    }
    if (modal) {
        modal.classList.remove('hidden');
        modal.classList.add('flex');
        const firstField = document.getElementById('cust-firstname');
        if (firstField) firstField.focus();
    }
}

/**
 * Close the New Customer registration modal.
 */
function closeNewCustomerModal() {
    const modal = document.getElementById('new-customer-modal');
    if (modal) {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
    }
}

/**
 * Handle AJAX submission of the new customer registration form.
 * Calls /api/customer/create, updates customer combobox, selects the new customer,
 * and notifies the user. Ensures already-existing customers are never duplicated.
 * @param {Event} e - Form submit event.
 */
async function handleNewCustomerSubmit(e) {
    e.preventDefault();
    const form = e.target;
    const submitBtn = document.getElementById('new-customer-submit-btn');
    const errBox = document.getElementById('new-customer-error');

    const payload = {
        firstname: form.firstname.value.trim(),
        lastname: form.lastname.value.trim(),
        dob: form.dob.value,
        gender: form.gender.value,
        phone_number: form.phone_number.value.trim(),
        email: form.email.value.trim(),
        address: form.address.value.trim(),
    };

    if (errBox) {
        errBox.classList.add('hidden');
        errBox.textContent = '';
    }

    if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.textContent = 'Registering...';
    }

    try {
        const response = await fetch('/api/customer/create', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(payload),
        });

        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.error || 'Failed to register customer profile.');
        }

        const targetCust = data.customer;

        // If newly created, add to customer directory
        const existsInMemory = bankCustomers.some(c => c.customer_id === targetCust.customer_id);
        if (!existsInMemory) {
            bankCustomers.unshift(targetCust);
        }

        // Auto-select in account creation modal
        selectCustomer(targetCust);

        // Close modal and show notification
        closeNewCustomerModal();
        if (data.already_exists) {
            showToast(data.message || `Customer #${targetCust.customer_id} already exists. Selected existing profile.`, 'info');
        } else {
            showToast(data.message || 'Customer registered and selected successfully!', 'success');
        }
    } catch (err) {
        if (errBox) {
            errBox.textContent = err.message;
            errBox.classList.remove('hidden');
        }
        showToast(err.message, 'error');
    } finally {
        if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.textContent = 'Register Customer';
        }
    }
}

// Auto-initialize customer combobox when DOM is loaded
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initCustomerCombobox);
} else {
    initCustomerCombobox();
}

// ============================================================================
// BANK PORTAL: ACCOUNT PROFILE & PAYMENT CARD MANAGEMENT CONTROLLER
// ============================================================================

/** Active account ID being viewed in the profile modal */
let currentProfileAccountId = null;

/**
 * Open the Comprehensive Account Profile Modal and load full relational details:
 * account balance/type, customer personal identity, home branch, linked cards,
 * and ledger transaction history.
 * @param {number|string} accountId - Database ID of the target account.
 */
async function openAccountProfile(accountId) {
    currentProfileAccountId = accountId;
    const modal = document.getElementById('account-profile-modal');
    if (!modal) return;

    // Reset fields to loading state
    document.getElementById('profile-acc-num').textContent = 'Loading...';
    document.getElementById('profile-acc-status-badge').className = 'hidden';
    document.getElementById('profile-balance').textContent = '₹--';
    document.getElementById('profile-acc-type').textContent = '--';
    document.getElementById('profile-created-at').textContent = '--';
    document.getElementById('profile-cust-name').textContent = 'Loading...';
    document.getElementById('profile-cust-meta').textContent = '--';
    document.getElementById('profile-cust-phone').textContent = '--';
    document.getElementById('profile-cust-email').textContent = '--';
    document.getElementById('profile-cust-address').textContent = '--';
    document.getElementById('profile-branch-name').textContent = 'Loading...';
    document.getElementById('profile-branch-ifsc').textContent = '--';
    document.getElementById('profile-branch-ifsc-sub').textContent = '--';
    document.getElementById('profile-branch-address').textContent = '--';
    document.getElementById('profile-branch-pin').textContent = '--';
    document.getElementById('profile-cards-list').innerHTML = '<div class="col-span-full py-4 text-center text-zinc-500">Loading cards...</div>';
    document.getElementById('profile-tx-tbody').innerHTML = '<tr><td colspan="7" class="py-4 text-center text-zinc-500">Loading ledger records...</td></tr>';

    toggleIssueCardPanel(false);

    // Show modal
    modal.classList.remove('hidden');
    modal.classList.add('flex');

    try {
        const data = await fetchAPI(`/api/account/${accountId}/details`);
        renderAccountProfile(data);
    } catch (err) {
        showToast(`Failed to load profile for account #${accountId}: ${err.message}`, 'error');
        closeAccountProfile();
    }
}

/**
 * Close the Account Profile modal.
 */
function closeAccountProfile() {
    const modal = document.getElementById('account-profile-modal');
    if (modal) {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
    }
    currentProfileAccountId = null;
}

/**
 * Render the account profile payload into the modal DOM.
 * @param {object} data - Account profile payload with account, customer, branch, cards, and transactions.
 */
function renderAccountProfile(data) {
    const { account, customer, branch, cards, transactions } = data;

    // 1. Account header & ledger
    const accNumEl = document.getElementById('profile-acc-num');
    accNumEl.textContent = account.account_number;

    const badgeEl = document.getElementById('profile-acc-status-badge');
    badgeEl.textContent = account.status;
    badgeEl.className = 'px-2 py-0.5 rounded text-[10px] font-semibold ' + ({
        'ACTIVE': 'badge-active',
        'FROZEN': 'badge-warning',
        'CLOSED': 'badge-closed'
    }[account.status] || 'bg-slate-100 text-slate-700');

    const balanceEl = document.getElementById('profile-balance');
    balanceEl.textContent = `₹${account.balance.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    if (account.balance > 100000) {
        balanceEl.className = 'text-base font-bold text-emerald-600 font-mono';
    } else {
        balanceEl.className = 'text-base font-bold text-slate-900 font-mono';
    }

    document.getElementById('profile-acc-type').textContent = account.account_type;
    const typeBadge = document.getElementById('profile-acc-type-badge');
    if (typeBadge) typeBadge.textContent = account.account_type;
    document.getElementById('profile-created-at').textContent = account.created_at;

    // 2. Customer profile
    document.getElementById('profile-cust-id').textContent = `#${customer.customer_id}`;
    document.getElementById('profile-cust-name').textContent = customer.full_name;
    document.getElementById('profile-cust-meta').textContent = `Age: ${customer.age || 'N/A'} yrs • DOB: ${customer.dob} • Gender: ${customer.gender || 'N/A'}`;
    document.getElementById('profile-cust-phone').textContent = customer.phone_number;
    document.getElementById('profile-cust-email').textContent = customer.email;
    document.getElementById('profile-cust-address').textContent = customer.address;

    // 3. Branch details
    document.getElementById('profile-branch-name').textContent = branch.branch_name;
    document.getElementById('profile-branch-ifsc').textContent = branch.ifsc_code;
    document.getElementById('profile-branch-ifsc-sub').textContent = branch.ifsc_code;
    document.getElementById('profile-branch-address').textContent = branch.address;
    document.getElementById('profile-branch-pin').textContent = branch.pin_code;

    // 4. Linked Cards List
    renderProfileCards(cards);

    // 5. Transaction Records Table
    renderProfileTransactions(transactions);
}

/**
 * Render cards list in the account profile modal.
 * @param {Array<object>} cards - Array of card objects.
 */
function renderProfileCards(cards) {
    const container = document.getElementById('profile-cards-list');
    if (!container) return;

    if (!cards || cards.length === 0) {
        container.innerHTML = `
            <div class="col-span-full py-5 text-center text-slate-500 bg-slate-50 border border-dashed border-slate-200 rounded-xl">
                No payment cards currently linked to this account.
                <button type="button" onclick="toggleIssueCardPanel(true)" class="text-indigo-600 hover:underline block mx-auto mt-1 text-[11px] font-medium">
                    + Issue First Card
                </button>
            </div>
        `;
        return;
    }

    container.innerHTML = cards.map(c => {
        const isBlocked = c.status === 'BLOCKED';
        const isExpired = c.status === 'EXPIRED';
        const statusBadgeClass = isBlocked
            ? 'badge-closed'
            : isExpired
            ? 'badge-warning'
            : 'badge-active';

        // Format 16-digit card number in blocks of 4
        const formattedNumber = c.card_number.replace(/(\d{4})/g, '$1 ').trim();

        let actionHtml = '';
        if (isBlocked) {
            actionHtml = `
                <div class="pt-2 border-t border-slate-200 flex items-center justify-between">
                    <span class="text-[10px] text-rose-600 font-semibold flex items-center gap-1">
                        <span>🔒</span> Blocked
                    </span>
                    <button 
                        type="button" 
                        onclick="unblockCard('${c.card_id}')" 
                        class="px-2.5 py-1 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white text-[10px] font-semibold flex items-center gap-1 transition shadow-sm cursor-pointer"
                        title="Reactivate card and reset failed PIN attempts to 0"
                    >
                        <span>✓</span> Reactivate Card
                    </button>
                </div>
            `;
        } else if (!isExpired) {
            actionHtml = `
                <div class="pt-2 border-t border-slate-200 flex items-center justify-between text-[10px]">
                    <span class="text-emerald-600 font-medium flex items-center gap-1">
                        <span>●</span> Operational
                    </span>
                    <button 
                        type="button" 
                        onclick="toggleCardBlock('${c.card_id}', 'BLOCKED')" 
                        class="text-slate-500 hover:text-rose-600 underline transition cursor-pointer text-[10px]"
                        title="Lock/Block card if lost or compromised"
                    >
                        Block Card
                    </button>
                </div>
            `;
        } else {
            actionHtml = `
                <div class="pt-2 border-t border-slate-200 text-[10px] text-slate-500">
                    Expired Card (Issue new card above)
                </div>
            `;
        }

        return `
            <div class="bg-slate-50 border border-slate-200 rounded-xl p-3.5 space-y-2 relative overflow-hidden group hover:border-slate-300 transition shadow-sm">
                <div class="flex items-center justify-between">
                    <span class="text-[10px] font-bold uppercase tracking-wider text-indigo-600">${c.card_type}</span>
                    <span class="${statusBadgeClass} px-2 py-0.5 rounded text-[9px] font-semibold">${c.status}</span>
                </div>
                <div>
                    <div class="font-mono text-sm tracking-widest font-semibold text-slate-900">${formattedNumber}</div>
                    <div class="text-[10px] text-slate-500 flex items-center justify-between mt-1">
                        <span>Exp: <strong class="text-slate-700 font-mono">${c.expiry_date}</strong></span>
                        <span>Attempts: <strong class="${c.failed_pin_attempts > 0 ? 'text-amber-600 font-bold' : 'text-slate-700'} font-mono">${c.failed_pin_attempts}/3</strong></span>
                    </div>
                </div>
                ${actionHtml}
            </div>
        `;
    }).join('');
}

/**
 * Unblock a blocked card, reset failed attempts to 0, and refresh the profile.
 * @param {number|string} cardId - Database ID of the card.
 */
async function unblockCard(cardId) {
    if (!cardId) return;

    try {
        const data = await fetchAPI(`/api/card/${cardId}/unblock`, {
            method: 'POST'
        });

        showToast(data.message || 'Card successfully unblocked and set to ACTIVE!', 'success');

        // Refresh profile details to reflect updated card status
        if (currentProfileAccountId) {
            const updated = await fetchAPI(`/api/account/${currentProfileAccountId}/details`);
            renderAccountProfile(updated);
        }
    } catch (err) {
        showToast(err.message || 'Failed to unblock card.', 'error');
    }
}

/**
 * Toggle card status between ACTIVE and BLOCKED.
 * @param {number|string} cardId - Database ID of the card.
 * @param {'ACTIVE'|'BLOCKED'} newStatus - Target status.
 */
async function toggleCardBlock(cardId, newStatus) {
    if (!cardId) return;

    if (newStatus === 'BLOCKED' && !confirm('Are you sure you want to lock/block this card?')) {
        return;
    }

    try {
        const data = await fetchAPI(`/api/card/${cardId}/status`, {
            method: 'POST',
            body: JSON.stringify({ status: newStatus })
        });

        showToast(data.message || `Card status updated to ${newStatus}.`, 'info');

        // Refresh profile details
        if (currentProfileAccountId) {
            const updated = await fetchAPI(`/api/account/${currentProfileAccountId}/details`);
            renderAccountProfile(updated);
        }
    } catch (err) {
        showToast(err.message || 'Failed to update card status.', 'error');
    }
}

/**
 * Render transaction activity in the account profile modal.
 * @param {Array<object>} transactions - Array of transaction objects.
 */
function renderProfileTransactions(transactions) {
    const tbody = document.getElementById('profile-tx-tbody');
    if (!tbody) return;

    if (!transactions || transactions.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="7" class="py-5 text-center text-slate-400 italic">No transaction records found for this account.</td>
            </tr>
        `;
        return;
    }

    tbody.innerHTML = transactions.map(t => {
        const isDeposit = t.transaction_type === 'DEPOSIT';
        const isWithdrawal = t.transaction_type === 'WITHDRAWAL';
        const amountClass = isDeposit ? 'text-emerald-600 font-bold' : (isWithdrawal ? 'text-rose-600 font-bold' : 'text-slate-900 font-bold');
        const sign = isDeposit ? '+' : (isWithdrawal ? '-' : '');

        return `
            <tr class="hover:bg-slate-50 border-b border-slate-100 transition">
                <td class="py-2.5 px-3 font-mono text-indigo-600 font-semibold">#${t.transaction_id}</td>
                <td class="py-2.5 px-3 text-slate-500 font-mono text-[11px] whitespace-nowrap">${t.date_time}</td>
                <td class="py-2.5 px-3">
                    <span class="px-2 py-0.5 rounded-full text-[10px] font-semibold border ${isDeposit ? 'text-emerald-700 bg-emerald-50 border-emerald-200' : (isWithdrawal ? 'text-rose-700 bg-rose-50 border-rose-200' : 'text-indigo-700 bg-indigo-50 border-indigo-200')}">
                        ${t.transaction_type}
                    </span>
                </td>
                <td class="py-2.5 px-3 font-mono ${amountClass}">${sign}₹${t.amount.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
                <td class="py-2.5 px-3 text-slate-600">${t.transaction_method}</td>
                <td class="py-2.5 px-3 text-slate-700 truncate max-w-[200px]" title="${t.atm_location}">${t.atm_location}</td>
                <td class="py-2.5 px-3 font-mono text-slate-500 text-[11px]">${t.card_number !== 'N/A' ? '•••• ' + t.card_number : 'Direct'}</td>
            </tr>
        `;
    }).join('');
}

/**
 * Toggle the Issue New Card inline panel in the profile modal.
 * @param {boolean} [explicitState] - Optional explicit boolean state.
 */
function toggleIssueCardPanel(explicitState) {
    const panel = document.getElementById('issue-card-panel');
    if (!panel) return;

    if (typeof explicitState === 'boolean') {
        if (explicitState) panel.classList.remove('hidden');
        else panel.classList.add('hidden');
    } else {
        panel.classList.toggle('hidden');
    }

    if (!panel.classList.contains('hidden')) {
        const pinInput = document.getElementById('new-card-pin');
        if (pinInput) pinInput.focus();
    }
}

/**
 * Handle submission of the Issue Card form.
 * Calls /api/account/<accountId>/card/create, displays confirmation, and refreshes the cards.
 * @param {Event} e - Form submit event.
 */
async function handleIssueCardSubmit(e) {
    e.preventDefault();
    if (!currentProfileAccountId) {
        showToast('No active account selected.', 'error');
        return;
    }

    const submitBtn = document.getElementById('issue-card-btn');
    const cardType = document.getElementById('new-card-type').value;
    const pin = document.getElementById('new-card-pin').value.trim();
    const validityYears = document.getElementById('new-card-validity').value;

    if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.textContent = 'Issuing...';
    }

    try {
        const data = await fetchAPI(`/api/account/${currentProfileAccountId}/card/create`, {
            method: 'POST',
            body: JSON.stringify({
                card_type: cardType,
                pin: pin,
                validity_years: validityYears
            })
        });

        showToast(data.message || 'Card issued successfully!', 'success');
        toggleIssueCardPanel(false);

        // Refresh account details to show the new card immediately
        const updatedData = await fetchAPI(`/api/account/${currentProfileAccountId}/details`);
        renderAccountProfile(updatedData);
    } catch (err) {
        showToast(err.message || 'Failed to issue card', 'error');
    } finally {
        if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.textContent = 'Issue Card';
        }
    }
}

// ============================================================================
// GLOBAL INVARIANT CONTROLLER ALIASES
// ============================================================================
window.keypadPress = window.keypadPress || function(char) {
    if (typeof appendPin === 'function') appendPin(char);
};
window.keypadClear = window.keypadClear || function() {
    if (typeof clearPin === 'function') clearPin();
};
window.handleLogin = window.handleLogin || function() {
    const form = document.getElementById('atm-login-form') || document.querySelector('form');
    if (form) form.submit();
};
window.submitWithdraw = window.submitWithdraw || function(amount) {
    if (typeof setWithdrawAmount === 'function' && amount) setWithdrawAmount(amount);
    const form = document.querySelector('#view-withdraw form') || document.querySelector('form[action="/withdraw"]');
    if (form) form.submit();
};
window.handleLogout = window.handleLogout || function() {
    window.location.href = '/logout';
};
window.fetchMiniStatement = window.fetchMiniStatement || function() {
    window.location.reload();
};


