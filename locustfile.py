"""
Load test for the e-commerce REST API.

Two kinds of virtual user, weighted like real traffic (most visitors only browse):

  BrowseUser   anonymous visitor: lists, filters, searches and opens products
  ShopperUser  registers, browses, uses the wishlist, reviews and places orders

Every response is validated (status and content), not just timed, so a fast error page counts as a failure.
Dynamic URLs are grouped under one name (for example "/products/[id]") so the statistics stay readable
and the thresholds in thresholds.json can refer to them.
"""
import random
import uuid

from locust import HttpUser, between, task

PASSWORD = "TestPass123!"
SEARCH_TERMS = ["shirt", "phone", "code", "jacket", "monitor", "novel"]
CATEGORY_IDS = [1, 2, 3]


def checked(client, method, path, name, expected, validate=None, **kwargs):
    """
    Send a request and mark it failed unless the status is in `expected` and `validate(json)` returns no error.
    `validate` returns None when the body is fine, or a message describing the problem.
    Returns the response on success, otherwise None.
    """
    with client.request(method, path, name=name, catch_response=True, **kwargs) as response:
        if response.status_code not in expected:
            response.failure(f"{response.status_code}: {response.text[:150]}")
            return None
        if validate is not None:
            try:
                problem = validate(response.json())
            except ValueError:
                problem = "response is not JSON"
            if problem:
                response.failure(problem)
                return None
        response.success()
        return response


def is_product_list(body):
    if not isinstance(body, list):
        return "expected a list of products"
    if body and not {"id", "name", "price", "stock"} <= body[0].keys():
        return "product is missing fields"
    return None


class StoreUser(HttpUser):
    abstract = True
    wait_time = between(0.5, 2)

    def on_start(self):
        # Product ids with stock, read once per user so tasks can use real ids
        response = checked(self.client, "GET", "/products", "/products", {200}, is_product_list)
        self.products = response.json() if response else []

    def random_product(self):
        return random.choice(self.products) if self.products else None

    # -- shared browsing tasks -------------------------------------------------
    @task(5)
    def list_products(self):
        checked(self.client, "GET", "/products", "/products", {200}, is_product_list)

    @task(2)
    def filter_by_category(self):
        category = random.choice(CATEGORY_IDS)
        checked(self.client, "GET", f"/products?category_id={category}", "/products?category_id=[id]", {200}, is_product_list)

    @task(2)
    def search(self):
        term = random.choice(SEARCH_TERMS)
        checked(self.client, "GET", f"/products?search={term}", "/products?search=[term]", {200}, is_product_list)

    @task(1)
    def sort_by_price(self):
        checked(self.client, "GET", "/products?sort_by=price&order=ASC", "/products?sort_by=price", {200}, is_product_list)

    @task(3)
    def view_product(self):
        product = self.random_product()
        if product:
            checked(
                self.client, "GET", f"/products/{product['id']}", "/products/[id]", {200},
                lambda body: None if body.get("id") == product["id"] else "wrong product returned",
            )

    @task(1)
    def read_reviews(self):
        product = self.random_product()
        if product:
            checked(
                self.client, "GET", f"/reviews/{product['id']}", "/reviews/[id]", {200},
                lambda body: None if isinstance(body, list) else "expected a list of reviews",
            )


class BrowseUser(StoreUser):
    """Anonymous visitor who only reads the catalogue (the bulk of the traffic)."""
    weight = 7


class ShopperUser(StoreUser):
    """A new customer who signs up, then browses, saves, reviews and buys."""
    weight = 3

    def on_start(self):
        super().on_start()
        self.email = f"load_{uuid.uuid4().hex[:12]}@example.com"
        checked(
            self.client, "POST", "/auth/register", "/auth/register", {201},
            lambda body: None if body.get("user", {}).get("email") == self.email else "wrong user returned",
            json={"email": self.email, "password": PASSWORD},
        )

    @task(2)
    def wishlist_round_trip(self):
        product = self.random_product()
        if not product:
            return
        checked(self.client, "POST", "/wishlist", "/wishlist", {200, 201}, json={"product_id": product["id"]})
        checked(self.client, "GET", "/wishlist", "/wishlist", {200},
                lambda body: None if isinstance(body, list) else "expected a list")
        checked(self.client, "DELETE", f"/wishlist/{product['id']}", "/wishlist/[id]", {200})

    @task(1)
    def post_review(self):
        product = self.random_product()
        if product:
            checked(self.client, "POST", "/reviews", "/reviews", {201},
                    json={"product_id": product["id"], "rating": random.randint(1, 5), "comment": "Load test review"})

    @task(2)
    def place_order(self):
        product = self.random_product()
        if not product:
            return
        quantity = random.randint(1, 2)
        # 409 means the product sold out during the test, which is a correct business answer, not a failure
        checked(
            self.client, "POST", "/orders", "/orders", {201, 409},
            json={"items": [{"productId": product["id"], "quantity": quantity}]},
        )

    @task(1)
    def view_order_history(self):
        checked(self.client, "GET", "/orders/my-orders", "/orders/my-orders", {200},
                lambda body: None if isinstance(body, list) else "expected a list of orders")
