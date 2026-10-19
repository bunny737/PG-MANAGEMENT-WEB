import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, apiFetch: vi.fn() };
});

import { ApiError, apiFetch } from "@/lib/api";
import { buildContactSchema, ContactForm, type ContactFormLabels } from "../ContactForm";

const labels: ContactFormLabels = {
  name: "Your name",
  email: "Email",
  phone: "Phone",
  phoneOptional: "optional",
  message: "Message",
  submit: "Send message",
  submitting: "Sending...",
  successTitle: "Message sent",
  successBody: "Thank you.",
  sendAnother: "Send another message",
  errorThrottled: "Too many messages",
  errorNetwork: "Network problem",
  errorGeneric: "Something went wrong",
  honeypotLabel: "Leave this field empty",
  validation: {
    nameRequired: "Enter your name",
    emailInvalid: "Enter a valid email",
    phoneInvalid: "Enter a valid phone",
    messageShort: "Write a bit more",
    messageLong: "Message too long",
  },
};

const mockApi = vi.mocked(apiFetch);
const MESSAGE = "I run a 60-bed PG in Hyderabad and would like early access.";

function fill({ name = "Ravi Kumar", email = "ravi@example.com", phone = "", message = MESSAGE } = {}) {
  fireEvent.change(screen.getByLabelText(labels.name), { target: { value: name } });
  fireEvent.change(screen.getByLabelText(labels.email), { target: { value: email } });
  fireEvent.change(screen.getByLabelText(/^Phone/), { target: { value: phone } });
  fireEvent.change(screen.getByLabelText(labels.message), { target: { value: message } });
}
const submit = () => fireEvent.click(screen.getByRole("button", { name: labels.submit }));
const sentBody = () => JSON.parse((mockApi.mock.calls[0][1] as RequestInit).body as string);

describe("ContactForm", () => {
  beforeEach(() => {
    mockApi.mockReset();
  });

  it("posts the trimmed values to the public endpoint without credentials, then confirms", async () => {
    mockApi.mockResolvedValue({ status: "received" });
    render(<ContactForm labels={labels} />);
    fill({ name: "  Ravi Kumar ", phone: "+91 98765 43210" });
    submit();

    expect(await screen.findByRole("status")).toBeTruthy();
    expect(screen.getByText(labels.successTitle)).toBeTruthy();

    expect(mockApi).toHaveBeenCalledTimes(1);
    const [path, options] = mockApi.mock.calls[0];
    expect(path).toBe("/api/v1/public/contact/");
    expect(options).toMatchObject({ method: "POST", skipAuth: true });
    expect(sentBody()).toEqual({
      name: "Ravi Kumar",
      email: "ravi@example.com",
      phone: "+91 98765 43210",
      message: MESSAGE,
      website: "",
    });
  });

  it("treats the phone number as optional", async () => {
    mockApi.mockResolvedValue({ status: "received" });
    render(<ContactForm labels={labels} />);
    fill({ phone: "" });
    submit();
    await screen.findByText(labels.successTitle);
    expect(sentBody().phone).toBe("");
  });

  it("shows translated validation errors and sends nothing while the form is invalid", async () => {
    render(<ContactForm labels={labels} />);
    fill({ name: "R", email: "not-an-email", phone: "abc", message: "short" });
    submit();

    expect(await screen.findByText(labels.validation.nameRequired)).toBeTruthy();
    expect(screen.getByText(labels.validation.emailInvalid)).toBeTruthy();
    expect(screen.getByText(labels.validation.phoneInvalid)).toBeTruthy();
    expect(screen.getByText(labels.validation.messageShort)).toBeTruthy();
    expect(mockApi).not.toHaveBeenCalled();
    expect(screen.getByLabelText(labels.email).getAttribute("aria-invalid")).toBe("true");
  });

  it("passes whatever a bot typed into the hidden honeypot through to the API", async () => {
    mockApi.mockResolvedValue({ status: "received" });
    render(<ContactForm labels={labels} />);
    fill();
    fireEvent.change(screen.getByLabelText(labels.honeypotLabel), { target: { value: "http://spam.example" } });
    submit();
    await screen.findByText(labels.successTitle);
    expect(sentBody().website).toBe("http://spam.example");
  });

  it("keeps the honeypot out of the tab order and away from assistive tech", () => {
    render(<ContactForm labels={labels} />);
    const trap = screen.getByLabelText(labels.honeypotLabel, { selector: "input" });
    expect(trap.getAttribute("tabindex")).toBe("-1");
    expect(trap.getAttribute("autocomplete")).toBe("off");
    expect(trap.closest("[aria-hidden='true']")).not.toBeNull();
    expect(trap.getAttribute("name")).not.toMatch(/website|url/i); // browsers autofill those
  });

  it("maps server field errors onto the fields", async () => {
    mockApi.mockRejectedValue(new ApiError(400, { email: ["The server rejected this address."] }));
    render(<ContactForm labels={labels} />);
    fill();
    submit();
    expect(await screen.findByText("The server rejected this address.")).toBeTruthy();
    expect(screen.queryByText(labels.successTitle)).toBeNull();
    expect(screen.getByRole("button", { name: labels.submit })).toBeTruthy();
  });

  it("explains a throttled request (429) in the visitor's language", async () => {
    mockApi.mockRejectedValue(new ApiError(429, { detail: "Request was throttled." }));
    render(<ContactForm labels={labels} />);
    fill();
    submit();
    expect((await screen.findByRole("alert")).textContent).toBe(labels.errorThrottled);
    expect(screen.queryByText("Request was throttled.")).toBeNull();
  });

  it("reports an unreachable server with the translated message, not apiFetch's English one", async () => {
    mockApi.mockRejectedValue(new ApiError(0, { detail: "Could not reach the server." }));
    render(<ContactForm labels={labels} />);
    fill();
    submit();
    expect((await screen.findByRole("alert")).textContent).toBe(labels.errorNetwork);
  });

  it("treats an unexpected non-API error as a network problem", async () => {
    mockApi.mockRejectedValue(new TypeError("Failed to fetch"));
    render(<ContactForm labels={labels} />);
    fill();
    submit();
    expect((await screen.findByRole("alert")).textContent).toBe(labels.errorNetwork);
  });

  it("falls back to a generic message for a server error with no field detail", async () => {
    mockApi.mockRejectedValue(new ApiError(500, { detail: "boom" }));
    render(<ContactForm labels={labels} />);
    fill();
    submit();
    expect((await screen.findByRole("alert")).textContent).toBe(labels.errorGeneric);
  });

  it("disables the button while sending so it cannot be double-submitted", async () => {
    let finish!: (value: unknown) => void;
    mockApi.mockReturnValue(new Promise((resolve) => (finish = resolve)));
    render(<ContactForm labels={labels} />);
    fill();
    submit();

    const busy = await screen.findByRole("button", { name: labels.submitting });
    expect((busy as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(busy);
    expect(mockApi).toHaveBeenCalledTimes(1);

    finish({ status: "received" });
    await screen.findByText(labels.successTitle);
  });

  it("lets the visitor send another message from a clean form", async () => {
    mockApi.mockResolvedValue({ status: "received" });
    render(<ContactForm labels={labels} />);
    fill();
    submit();
    await screen.findByText(labels.successTitle);

    fireEvent.click(screen.getByRole("button", { name: labels.sendAnother }));
    await waitFor(() => expect(screen.getByLabelText(labels.name)).toBeTruthy());
    expect((screen.getByLabelText(labels.name) as HTMLInputElement).value).toBe("");
    expect((screen.getByLabelText(labels.message) as HTMLTextAreaElement).value).toBe("");
  });

  it("links every label to its input", () => {
    render(<ContactForm labels={labels} />);
    for (const label of [labels.name, labels.email, labels.message]) {
      expect(screen.getByLabelText(label)).toBeTruthy();
    }
    expect(screen.getByLabelText(/^Phone/)).toBeTruthy();
  });
});

describe("buildContactSchema", () => {
  const schema = buildContactSchema(labels.validation);
  const base = { name: "Ravi", email: "r@example.com", phone: "", message: MESSAGE };
  const ok = (patch: Partial<typeof base>) => schema.safeParse({ ...base, ...patch }).success;

  it("enforces the same bounds as the backend serializer", () => {
    expect(ok({})).toBe(true);
    expect(ok({ name: "R" })).toBe(false);
    expect(ok({ name: "Ra" })).toBe(true);
    expect(ok({ name: "x".repeat(101) })).toBe(false);
    expect(ok({ message: "123456789" })).toBe(false);
    expect(ok({ message: "1234567890" })).toBe(true);
    expect(ok({ message: "x".repeat(2000) })).toBe(true);
    expect(ok({ message: "x".repeat(2001) })).toBe(false);
    expect(ok({ email: "a@b" })).toBe(false);
  });

  it("accepts Indian-style numbers and rejects junk", () => {
    for (const good of ["", "9876543210", "+91 98765 43210", "+919876543210", "1234567"]) {
      expect(ok({ phone: good }), good).toBe(true);
    }
    for (const bad of ["abc", "12345", "98-765-43210", "+" + "9".repeat(16), "+".repeat(3)]) {
      expect(ok({ phone: bad }), bad).toBe(false);
    }
  });
});
