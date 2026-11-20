// MyMarketplace API client (corrected version of the supplied api.js).
// Change this default if your API is running somewhere else.
const BASE_URL = "http://localhost:9999";

class MarketplaceAPIError extends Error {
    constructor(message, status = 0, details = null) {
        super(message);
        this.name = "MarketplaceAPIError";
        this.status = status;
        this.details = details;
    }
}

class MyMarketplaceAPI {
    constructor(base_url = BASE_URL) {
        this.base_url = String(base_url).replace(/\/+$/, "");
    }

    async _request(path, { method = "GET", body, credentials = false } = {}) {
        const url = `${this.base_url}${path}`;
        const headers = { Accept: "application/json" };
        if (body !== undefined) headers["Content-Type"] = "application/json";

        let response;
        try {
            response = await fetch(url, {
                method,
                headers,
                credentials: credentials ? "include" : "omit",
                ...(body !== undefined ? { body: JSON.stringify(body) } : {})
            });
        } catch (error) {
            throw new MarketplaceAPIError(
                "Could not reach the API. Check the server URL and CORS settings.",
                0,
                error
            );
        }

        // Success responses may be empty (200, as in Successful, or 204).
        const raw = response.status === 204 ? "" : await response.text();
        let data = null;
        if (raw) {
            try {
                data = JSON.parse(raw);
            } catch {
                if (response.ok) {
                    throw new MarketplaceAPIError("The API returned invalid JSON.", response.status);
                }
                data = { message: raw };
            }
        }

        if (!response.ok) {
            throw new MarketplaceAPIError(
                data && typeof data.message === "string"
                    ? data.message
                    : `Request failed (HTTP ${response.status}).`,
                response.status,
                data
            );
        }
        return data;
    }

    // Health
    health() {
        return this._request("/health");
    }

    // User
    register_user(username, password) {
        return this._request("/user/register", {
            method: "POST", body: { username, password }, credentials: true
        });
    }

    login_user(username, password) {
        return this._request("/user/login", {
            method: "POST", body: { username, password }, credentials: true
        });
    }

    logout_user() {
        return this._request("/user/logout", { credentials: true });
    }

    edit_user(uuid, new_username = null, new_password = null) {
        const body = { uuid }; // Required by UserModel_Partial in main(5).tsp.
        if (new_username !== null && new_username !== "") body.username = new_username;
        if (new_password !== null && new_password !== "") body.password = new_password;
        if (Object.keys(body).length === 1) {
            throw new Error("Enter a username or password to update.");
        }
        return this._request("/user", { method: "PATCH", body, credentials: true });
    }

    delete_user() {
        return this._request("/user", { method: "DELETE", credentials: true });
    }

    // Preserve the method name in the originally supplied API client.
    delete() {
        return this.delete_user();
    }

    // Products
    list_products() {
        return this._request("/products", { credentials: true });
    }

    search_product(name) {
        return this._request(`/products/search?q=${encodeURIComponent(name)}`, {
            credentials: true
        });
    }

    get_product(uuid) {
        return this._request(`/products/${encodeURIComponent(uuid)}`, {
            credentials: true
        });
    }

    // Cart
    list_cart() {
        return this._request("/cart", { credentials: true });
    }

    // CartAddition in main(5).tsp: { product: UUIDv4, quantity: 1..1000 }.
    // Successful status is HTTP 200, without a response body.
    add_to_cart(product_uuid, quantity = 1) {
        if (typeof product_uuid !== "string" ||
            !/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(product_uuid)) {
            throw new Error("A valid product UUIDv4 is required.");
        }
        if (!Number.isInteger(quantity) || quantity < 1 || quantity > 1000) {
            throw new Error("Quantity must be a whole number between 1 and 1000.");
        }
        return this._request("/cart", {
            method: "POST",
            body: { product: product_uuid, quantity },
            credentials: true
        });
    }

    edit_cart(index, body) {
        return this._request(`/cart?index=${encodeURIComponent(index)}`, {
            method: "PATCH", body, credentials: true
        });
    }

    delete_cart(index) {
        return this._request(`/cart?index=${encodeURIComponent(index)}`, {
            method: "DELETE", credentials: true
        });
    }

    clear_cart() {
        return this._request("/cart/clear", { method: "DELETE", credentials: true });
    }
}

// Also expose the client for non-module scripts or browser-console debugging.
window.MyMarketplaceAPI = MyMarketplaceAPI;
window.MarketplaceAPIError = MarketplaceAPIError;
window.MARKETPLACE_DEFAULT_API_URL = BASE_URL;
