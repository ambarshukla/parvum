import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { App } from "./App";

afterEach(() => {
    vi.restoreAllMocks();
});

describe("App", () => {
    it("shows the login page when there is no valid session", async () => {
        vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(null, { status: 401 }));
        render(<App />);
        await waitFor(() => expect(screen.getByLabelText("Password")).toBeInTheDocument());
    });

    it("shows the signed-in shell when a session cookie is already valid", async () => {
        vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(null, { status: 204 }));
        render(<App />);
        await waitFor(() => expect(screen.getByText("Sign out")).toBeInTheDocument());
    });
});
