(() => {
    "use strict";

    const $ = (id) => document.getElementById(id);
    const DEFAULT_URL = window.MARKETPLACE_DEFAULT_API_URL || "http://localhost:9999";
    const API_URL_KEY = "mymarketplace.apiUrl";
    const SESSION_KEY_PREFIX = "mymarketplace.user.";

    function readStorage(storeName, key) {
        try { return window[storeName].getItem(key); } catch { return null; }
    }

    function writeStorage(storeName, key, value) {
        try {
            const store = window[storeName];
            if (value === null) store.removeItem(key);
            else store.setItem(key, value);
        } catch { /* Storage is optional (e.g. private browsing). */ }
    }

    function normalizeUrl(value) {
        const parsed = new URL(value.trim());
        if (!["http:", "https:"].includes(parsed.protocol)) {
            throw new Error("Use an http:// or https:// API URL.");
        }
        if (parsed.username || parsed.password || parsed.search || parsed.hash) {
            throw new Error("Enter a base URL without credentials, a query, or a fragment.");
        }
        return parsed.href.replace(/\/+$/, "");
    }

    let apiUrl;
    try { apiUrl = normalizeUrl(readStorage("localStorage", API_URL_KEY) || DEFAULT_URL); }
    catch { apiUrl = DEFAULT_URL; }
    let api = new MyMarketplaceAPI(apiUrl);
    let user = restoreUser();
    let products = [];
    let currentQuery = "";
    let productRequestNumber = 0;
    let cartRequestNumber = 0;
    let cartBusy = false;
    let toastTimer = null;
    let authMode = "login";

    function restoreUser() {
        const raw = readStorage("sessionStorage", SESSION_KEY_PREFIX + apiUrl);
        if (!raw) return null;
        try {
            const saved = JSON.parse(raw);
            return saved && typeof saved.uuid === "string" && typeof saved.username === "string"
                ? saved : null;
        } catch { return null; }
    }

    function setUser(nextUser) {
        user = nextUser && nextUser.uuid && nextUser.username
            ? { uuid: nextUser.uuid, username: nextUser.username }
            : null;
        writeStorage("sessionStorage", SESSION_KEY_PREFIX + apiUrl,
            user ? JSON.stringify(user) : null);
        updateAccountUI();
    }

    function errorMessage(error) {
        if (error && error.status === 401) return "You are not signed in, or your session has expired. Please log in.";
        if (error && error.status === 403) return "You do not have permission to do that.";
        return error && error.message ? error.message : "Something went wrong. Please try again.";
    }

    function handleAuthError(error) {
        if (error && (error.status === 401 || error.status === 403) && user) setUser(null);
    }

    function showMessage(id, message, kind = "info") {
        const node = $(id);
        node.hidden = !message;
        node.textContent = message || "";
        node.className = `message-panel message-${kind}`;
    }

    function toast(message, kind = "success") {
        const node = $("toast");
        clearTimeout(toastTimer);
        node.textContent = message;
        node.className = `toast toast-${kind}`;
        node.hidden = false;
        toastTimer = setTimeout(() => { node.hidden = true; }, 4500);
    }

    async function withButton(button, callback) {
        if (button.disabled) return;
        button.disabled = true;
        try { await callback(); }
        finally { button.disabled = false; }
    }

    function el(tag, className, text) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined) node.textContent = String(text);
        return node;
    }

    function formatPrice(value) {
        const amount = Number(value);
        return Number.isFinite(amount) ? amount.toFixed(2) : "—";
    }

    function stockLabel(item) {
        const stock = Number(item.stock);
        return !Number.isFinite(stock) ? "Stock unknown"
            : stock === 0 ? "Out of stock" : `${stock} in stock`;
    }

    function navigate(view) {
        for (const name of ["shop", "cart", "account"]) {
            $(`${name}-view`).hidden = name !== view;
        }
        document.querySelectorAll(".site-nav [data-view]").forEach((button) => {
            const selected = button.dataset.view === view;
            button.classList.toggle("is-active", selected);
            if (selected) button.setAttribute("aria-current", "page");
            else button.removeAttribute("aria-current");
        });
        if (view === "cart") loadCart();
    }

    async function checkHealth() {
        const badge = $("connection-badge");
        const status = $("connection-text");
        badge.className = "connection-badge";
        status.textContent = "Checking...";
        badge.title = "Checking API health";
        const checkedApi = api;
        try {
            const result = await checkedApi.health();
            if (checkedApi !== api) return;
            badge.classList.add("is-online");
            status.textContent = "API online";
            badge.title = `API health: ${result?.status || "Connected"}`;
        } catch (error) {
            if (checkedApi !== api) return;
            badge.classList.add("is-offline");
            status.textContent = "API offline";
            badge.title = errorMessage(error);
        }
    }

    function renderProducts() {
        const grid = $("product-grid");
        grid.replaceChildren();
        const sorted = [...products];
        switch ($("sort-products").value) {
            case "price-low": sorted.sort((a, b) => Number(a.price) - Number(b.price)); break;
            case "price-high": sorted.sort((a, b) => Number(b.price) - Number(a.price)); break;
            case "name": sorted.sort((a, b) => String(a.name).localeCompare(String(b.name))); break;
        }

        if (!sorted.length) {
            showMessage("products-message", currentQuery
                ? `No products found for “${currentQuery}”.`
                : "No products are available yet.");
            return;
        }
        showMessage("products-message", "");
        const template = $("product-card-template");
        sorted.forEach((item, index) => {
            const card = template.content.firstElementChild.cloneNode(true);
            const button = card.querySelector(".product-card-button");
            const art = card.querySelector(".product-art");
            art.dataset.tone = String(index % 4);
            card.querySelector(".product-eyebrow").textContent = item.seller?.username
                ? `BY ${item.seller.username}` : "MARKETPLACE PRODUCT";
            card.querySelector(".product-name").textContent = item.name || "Unnamed product";
            card.querySelector(".product-meta").textContent = `${stockLabel(item)} · ${(item.sizes || []).length} sizes`;
            card.querySelector(".product-price").textContent = formatPrice(item.price);
            button.setAttribute("aria-label", `View details for ${item.name || "product"}`);
            button.addEventListener("click", () => openProduct(item.uuid));

            const addButton = card.querySelector(".add-to-cart-button");
            // main.tsp does not define a stock-based restriction on CartAddition.
            // Let the API decide whether a product can actually be added.
            addButton.setAttribute("aria-label", `Add one ${item.name || "product"} to cart`);
            addButton.addEventListener("click", () => addProductToCart(item, 1, addButton));
            grid.append(card);
        });
    }

    async function loadProducts(query = currentQuery) {
        const request = ++productRequestNumber;
        const currentApi = api;
        showMessage("products-message", "Loading products...");
        $("product-grid").replaceChildren();
        $("products-summary").textContent = "Loading products...";
        try {
            const result = query ? await currentApi.search_product(query) : await currentApi.list_products();
            if (request !== productRequestNumber || currentApi !== api) return;
            if (!Array.isArray(result)) throw new Error("Unexpected products response from API.");
            products = result;
            $("products-summary").textContent = `${result.length} product${result.length === 1 ? "" : "s"}${query ? ` matching “${query}”` : ""} · Prices shown without a currency symbol`;
            renderProducts();
        } catch (error) {
            if (request !== productRequestNumber || currentApi !== api) return;
            products = [];
            $("products-summary").textContent = "Unable to load products";
            $("product-grid").replaceChildren();
            if (error.status === 404) {
                $("products-summary").textContent = "0 products found";
                renderProducts();
            } else {
                handleAuthError(error);
                showMessage("products-message", errorMessage(error), "error");
            }
        }
    }

    async function addProductToCart(item, quantity, button) {
        if (!item || !item.uuid) {
            toast("This product has no valid ID.", "error");
            return;
        }
        if (!Number.isInteger(quantity) || quantity < 1 || quantity > 1000) {
            toast("Enter a whole-number quantity between 1 and 1000.", "error");
            return;
        }

        const currentApi = api;
        await withButton(button, async () => {
            try {
                await currentApi.add_to_cart(item.uuid, quantity);
                if (currentApi !== api) return;
                toast(`${quantity} × ${item.name || "Product"} added to cart.`);
                await loadCart(); // Refresh the nav badge and cart immediately.
            } catch (error) {
                if (currentApi !== api) return;
                handleAuthError(error);
                toast(errorMessage(error), "error");
                if (error && error.status === 401) navigate("account");
            }
        });
    }

    function addDefinition(list, term, value) {
        list.append(el("dt", "", term), el("dd", "", value));
    }

    function appendChips(parent, label, values) {
        const group = el("div", "detail-group");
        group.append(el("h4", "", label));
        const items = el("div", "chip-list");
        if (Array.isArray(values) && values.length) {
            values.forEach(value => items.append(el("span", "chip", value)));
        } else {
            items.append(el("span", "muted", "None listed"));
        }
        group.append(items);
        parent.append(group);
    }

    function renderProductDetail(item) {
        const root = $("product-detail-content");
        root.replaceChildren();
        const main = el("div", "detail-layout");
        const art = el("div", "detail-art");
        const artCopy = $("product-card-template").content.querySelector(".product-art").cloneNode(true);
        art.append(artCopy);
        const info = el("div", "detail-info");
        info.append(el("p", "eyebrow", item.seller?.username ? `SOLD BY ${item.seller.username}` : "PRODUCT"));
        info.append(el("h3", "detail-name", item.name || "Unnamed product"));
        info.append(el("p", "detail-price", formatPrice(item.price)));
        info.append(el("p", "muted", `Price currency is not specified · ${stockLabel(item)}`));
        appendChips(info, "Available sizes", item.sizes);
        appendChips(info, "Available colors", item.colors);

        const addForm = el("form", "detail-add-form");
        const quantityLabel = el("label", "", "Quantity");
        const quantityInput = el("input", "quantity-input");
        quantityInput.type = "number";
        quantityInput.min = "1";
        quantityInput.max = "1000";
        quantityInput.step = "1";
        quantityInput.value = "1";
        quantityInput.required = true;
        quantityLabel.append(quantityInput);
        const addButton = el("button", "button button-primary", "Add to cart");
        addButton.type = "submit";
        addForm.append(quantityLabel, addButton);
        addForm.addEventListener("submit", (event) => {
            event.preventDefault();
            if (!addForm.reportValidity()) return;
            addProductToCart(item, Number(quantityInput.value), addButton);
        });
        info.append(addForm);
        main.append(art, info);
        root.append(main);
        const refs = el("dl", "detail-references");
        addDefinition(refs, "Product ID", item.uuid || "Unknown");
        addDefinition(refs, "Seller ID", item.seller?.uuid || "Unknown");
        addDefinition(refs, "Image references", Array.isArray(item.images) && item.images.length
            ? item.images.join(", ") : "No images listed");
        root.append(refs);
        root.append(el("p", "muted small-note", "The API supplies image UUIDs, but does not document a URL for downloading images."));
    }

    async function openProduct(uuid) {
        const dialog = $("product-dialog");
        $("product-detail-content").replaceChildren(el("p", "muted", "Loading details..."));
        if (!dialog.open) dialog.showModal();
        const currentApi = api;
        try {
            const item = await currentApi.get_product(uuid);
            if (currentApi !== api || !dialog.open) return;
            renderProductDetail(item);
        } catch (error) {
            if (currentApi !== api || !dialog.open) return;
            $("product-detail-content").replaceChildren(el("p", "error-text", errorMessage(error)));
        }
    }

    function updateCartBadge(count) {
        const badge = $("cart-count");
        badge.hidden = count <= 0;
        badge.textContent = String(count);
    }

    function setCartButtonsDisabled(disabled) {
        $("cart-items").querySelectorAll("button, input").forEach((element) => {
            element.disabled = disabled;
        });
        $("clear-cart").disabled = disabled;
    }

    async function cartMutation(operation, success) {
        if (cartBusy) return;
        cartBusy = true;
        setCartButtonsDisabled(true);
        try {
            await operation();
            toast(success);
            await loadCart();
        } catch (error) {
            handleAuthError(error);
            toast(errorMessage(error), "error");
        } finally {
            cartBusy = false;
            setCartButtonsDisabled(false);
        }
    }

    function renderCart(items) {
        const root = $("cart-items");
        root.replaceChildren();
        $("cart-footer").hidden = !items.length;
        // CartModel.items uses PoductModel_Quantified (the name in main.tsp),
        // so each line has a required integer quantity between 1 and 1000.
        const units = items.reduce((total, item) => total + item.quantity, 0);
        const subtotal = items.reduce((total, item) => total + item.price * item.quantity, 0);
        $("cart-summary").textContent =
            `${items.length} product${items.length === 1 ? "" : "s"} · ` +
            `${units} unit${units === 1 ? "" : "s"} · ` +
            `Subtotal: ${formatPrice(subtotal)} (currency unspecified)`;

        if (!items.length) {
            showMessage("cart-message", "Your cart is empty. There are no items to manage.");
            return;
        }
        showMessage("cart-message", "");
        items.forEach((item, index) => {
            const row = el("article", "cart-item");
            const thumb = el("div", "cart-thumb", "◈");
            thumb.setAttribute("aria-hidden", "true");
            const info = el("div", "cart-item-info");
            const title = el("button", "cart-item-name", item.name || "Unnamed product");
            title.type = "button";
            title.addEventListener("click", () => openProduct(item.uuid));
            info.append(title);
            info.append(el("p", "muted", `Seller: ${item.seller?.username || "Unknown"}`));
            info.append(el("p", "cart-item-price", `${formatPrice(item.price)} each`));
            info.append(el("p", "cart-line-total",
                `${item.quantity} × ${formatPrice(item.price)} = ${formatPrice(item.price * item.quantity)}`));

            const form = el("form", "cart-quantity-form");
            const label = el("label", "", "Set quantity");
            const qty = el("input", "quantity-input");
            qty.type = "number";
            qty.min = "1";
            qty.max = "1000";
            qty.step = "1";
            qty.required = true;
            qty.value = String(item.quantity);
            qty.setAttribute("aria-label", `Quantity for ${item.name || "product"}`);
            label.append(qty);
            const update = el("button", "button button-outline button-small", "Update");
            update.type = "submit";
            form.append(label, update);
            form.addEventListener("submit", (event) => {
                event.preventDefault();
                if (!form.reportValidity()) return;
                const value = Number(qty.value);
                if (!Number.isInteger(value) || value < 1 || value > 1000) {
                    toast("Quantity must be an integer from 1 to 1000.", "error");
                    return;
                }
                cartMutation(() => api.edit_cart(index, { quantity: value }), "Quantity updated.");
            });

            const remove = el("button", "button button-quiet remove-item", "Remove");
            remove.type = "button";
            remove.setAttribute("aria-label", `Remove ${item.name || "product"} from cart`);
            remove.addEventListener("click", () => {
                if (window.confirm(`Remove ${item.name || "this item"} from your cart?`)) {
                    cartMutation(() => api.delete_cart(index), "Item removed from cart.");
                }
            });
            row.append(thumb, info, form, remove);
            root.append(row);
        });
    }

    async function loadCart() {
        const request = ++cartRequestNumber;
        const currentApi = api;
        showMessage("cart-message", "Loading cart...");
        $("cart-items").replaceChildren();
        $("cart-footer").hidden = true;
        try {
            const result = await currentApi.list_cart();
            if (request !== cartRequestNumber || currentApi !== api) return;
            if (!result || !Array.isArray(result.items)) throw new Error("Unexpected cart response from API.");
            // On a fresh page, the cart may be the only endpoint that identifies the session owner.
            if (result.owner?.uuid && result.owner?.username &&
                (!user || user.uuid !== result.owner.uuid)) setUser(result.owner);
            updateCartBadge(result.items.reduce((total, item) => total + item.quantity, 0));
            renderCart(result.items);
        } catch (error) {
            if (request !== cartRequestNumber || currentApi !== api) return;
            updateCartBadge(0);
            $("cart-items").replaceChildren();
            $("cart-footer").hidden = true;
            if (error.status === 404) {
                renderCart([]); // Documented 404: cart is empty.
            } else {
                handleAuthError(error);
                showMessage("cart-message", errorMessage(error), "error");
            }
        }
    }

    function setAuthMode(mode) {
        authMode = mode;
        const register = mode === "register";
        $("login-tab").classList.toggle("is-active", !register);
        $("login-tab").setAttribute("aria-selected", String(!register));
        $("register-tab").classList.toggle("is-active", register);
        $("register-tab").setAttribute("aria-selected", String(register));
        $("auth-heading").textContent = register ? "Create an account" : "Welcome back";
        $("auth-description").textContent = register
            ? "Set up your marketplace profile in a few steps."
            : "Sign in to manage your account and cart.";
        $("auth-submit").textContent = register ? "Create account" : "Log in";
        // main(5).tsp uses Password for both login and registration.
        $("auth-password").setAttribute("autocomplete", register ? "new-password" : "current-password");
        $("auth-password").value = "";
    }

    function updateAccountUI() {
        $("signed-out-panel").hidden = !!user;
        $("signed-in-panel").hidden = !user;
        $("user-badge").textContent = user ? user.username : "Guest";
        $("cart-guest-hint").hidden = !!user;
        if (!user) return;
        $("profile-username").textContent = user.username;
        $("profile-uuid").textContent = `User ID: ${user.uuid}`;
        $("profile-avatar").textContent = user.username[0].toUpperCase();
        $("new-username").value = user.username;
    }

    function setupEvents() {
        document.querySelectorAll("[data-view]").forEach(button => {
            button.addEventListener("click", () => navigate(button.dataset.view));
        });

        $("search-form").addEventListener("submit", event => {
            event.preventDefault();
            currentQuery = $("product-search").value.trim();
            $("clear-search").hidden = !currentQuery;
            loadProducts();
        });
        $("clear-search").addEventListener("click", () => {
            $("product-search").value = "";
            currentQuery = "";
            $("clear-search").hidden = true;
            loadProducts();
        });
        $("sort-products").addEventListener("change", renderProducts);
        $("refresh-products").addEventListener("click", () => loadProducts());
        $("refresh-cart").addEventListener("click", () => loadCart());
        $("clear-cart").addEventListener("click", () => {
            if (window.confirm("Remove all items from your cart?")) {
                cartMutation(() => api.clear_cart(), "Cart cleared.");
            }
        });

        $("login-tab").addEventListener("click", () => setAuthMode("login"));
        $("register-tab").addEventListener("click", () => setAuthMode("register"));
        $("auth-form").addEventListener("submit", event => {
            event.preventDefault();
            const button = $("auth-submit");
            withButton(button, async () => {
                const username = $("auth-username").value.trim();
                const password = $("auth-password").value;
                try {
                    if (authMode === "register") {
                        await api.register_user(username, password);
                        $("auth-password").value = "";
                        setAuthMode("login");
                        toast("Account created. Please log in.");
                    } else {
                        const account = await api.login_user(username, password);
                        if (!account?.uuid || !account?.username) {
                            throw new Error("The API did not return a valid user profile.");
                        }
                        $("auth-password").value = "";
                        setUser(account);
                        toast(`Welcome back, ${account.username}!`);
                        await loadCart();
                    }
                } catch (error) {
                    toast(errorMessage(error), "error");
                }
            });
        });

        $("logout-button").addEventListener("click", event => {
            withButton(event.currentTarget, async () => {
                try {
                    await api.logout_user();
                    setUser(null);
                    updateCartBadge(0);
                    $("cart-items").replaceChildren();
                    toast("Logged out successfully.");
                } catch (error) { toast(errorMessage(error), "error"); }
            });
        });

        $("username-form").addEventListener("submit", event => {
            event.preventDefault();
            const button = event.currentTarget.querySelector("button[type='submit']");
            withButton(button, async () => {
                if (!user) return;
                const username = $("new-username").value.trim();
                if (username === user.username) { toast("Your username is unchanged."); return; }
                try {
                    const updated = await api.edit_user(user.uuid, username, null);
                    setUser(updated?.uuid && updated?.username ? updated : { ...user, username });
                    toast("Username updated.");
                } catch (error) { handleAuthError(error); toast(errorMessage(error), "error"); }
            });
        });

        $("password-form").addEventListener("submit", event => {
            event.preventDefault();
            const button = event.currentTarget.querySelector("button[type='submit']");
            withButton(button, async () => {
                if (!user) return;
                try {
                    await api.edit_user(user.uuid, null, $("new-password").value);
                    $("new-password").value = "";
                    toast("Password updated.");
                } catch (error) { handleAuthError(error); toast(errorMessage(error), "error"); }
            });
        });

        $("delete-account").addEventListener("click", event => {
            if (!window.confirm("Permanently delete your account? This cannot be undone.")) return;
            withButton(event.currentTarget, async () => {
                try {
                    await api.delete_user();
                    setUser(null);
                    updateCartBadge(0);
                    $("cart-items").replaceChildren();
                    toast("Account deleted.");
                } catch (error) { toast(errorMessage(error), "error"); }
            });
        });

        $("api-url-form").addEventListener("submit", event => {
            event.preventDefault();
            try {
                const nextUrl = normalizeUrl($("api-url").value);
                if (nextUrl === apiUrl) { toast("API URL is already set."); return; }
                apiUrl = nextUrl;
                api = new MyMarketplaceAPI(apiUrl);
                writeStorage("localStorage", API_URL_KEY, apiUrl);
                setUser(restoreUser());
                products = [];
                currentQuery = "";
                $("product-search").value = "";
                $("clear-search").hidden = true;
                updateCartBadge(0);
                ++productRequestNumber;
                ++cartRequestNumber;
                navigate("shop");
                toast("API server updated.");
                checkHealth();
                loadProducts();
                loadCart();
            } catch (error) { toast(errorMessage(error), "error"); }
        });

        $("close-dialog").addEventListener("click", () => $("product-dialog").close());
        $("product-dialog").addEventListener("click", event => {
            if (event.target === $("product-dialog")) $("product-dialog").close();
        });
    }

    $("api-url").value = apiUrl;
    updateAccountUI();
    setupEvents();
    checkHealth();
    loadProducts();
    loadCart();
})();
