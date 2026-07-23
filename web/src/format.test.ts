import { describe, expect, it } from "vitest";
import { money, percent, longDate, monthLabel, multiple } from "./format";

describe("formatters", () => {
    it("money renders whole-dollar USD", () => {
        expect(money(41091835.83)).toBe("$41,091,836");
        expect(money(0)).toBe("$0");
    });

    it("percent scales a 0..1 weight", () => {
        expect(percent(0.2)).toBe("20.0%");
        expect(percent(0.6, 0)).toBe("60%");
        expect(percent(0.0265687243, 2)).toBe("2.66%");
    });

    it("longDate formats an ISO date without timezone drift", () => {
        expect(longDate("2026-07-17")).toBe("17 Jul 2026");
    });

    it("monthLabel formats a first-of-month ISO date", () => {
        expect(monthLabel("2026-06-01")).toBe("Jun 2026");
    });

    it("multiple renders a ratio with a trailing x", () => {
        expect(multiple(1.44)).toBe("1.44x");
        expect(multiple(0)).toBe("0.00x");
    });
});
