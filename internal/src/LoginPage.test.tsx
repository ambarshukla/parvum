import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { LoginPage } from "./LoginPage";

afterEach(() => {
    vi.restoreAllMocks();
});

describe("LoginPage", () => {
    it("calls onLoggedIn after a successful submit", async () => {
        vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(null, { status: 204 }));
        const onLoggedIn = vi.fn();
        render(<LoginPage onLoggedIn={onLoggedIn} />);

        fireEvent.change(screen.getByLabelText("Password"), { target: { value: "secret" } });
        fireEvent.click(screen.getByText("Sign in"));

        await waitFor(() => expect(onLoggedIn).toHaveBeenCalled());
    });

    it("shows an error and does not call onLoggedIn on a wrong password", async () => {
        vi.spyOn(globalThis, "fetch").mockResolvedValue(
            new Response(null, { status: 401, statusText: "Unauthorized" }),
        );
        const onLoggedIn = vi.fn();
        render(<LoginPage onLoggedIn={onLoggedIn} />);

        fireEvent.change(screen.getByLabelText("Password"), { target: { value: "wrong" } });
        fireEvent.click(screen.getByText("Sign in"));

        await waitFor(() => expect(screen.getByText("Wrong password.")).toBeInTheDocument());
        expect(onLoggedIn).not.toHaveBeenCalled();
    });
});
