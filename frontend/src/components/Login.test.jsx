import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api", async () => {
  const actual = await vi.importActual("../api");
  return { ...actual, login: vi.fn(), signup: vi.fn() };
});

import * as api from "../api";
import Login from "./Login";

beforeEach(() => {
  api.login.mockReset();
  api.signup.mockReset();
});

/** The mode tab and the submit button share a label ("Log in"), so the submit
 *  has to be picked by type rather than by name. */
const submitButton = () =>
  screen.getAllByRole("button").find((b) => b.getAttribute("type") === "submit");

const fillAndSubmit = async (email, password) => {
  await userEvent.type(screen.getByLabelText(/email/i), email);
  await userEvent.type(screen.getByLabelText(/password/i), password);
  await userEvent.click(submitButton());
};

describe("Login", () => {
  it("stores the token and reports the role on success", async () => {
    api.login.mockResolvedValue({ access_token: "tok123", role: "editor" });
    const onAuthed = vi.fn();
    render(<Login onAuthed={onAuthed} />);

    await fillAndSubmit("a@b.com", "correct-horse-battery");

    await waitFor(() => expect(onAuthed).toHaveBeenCalledWith("editor"));
    expect(localStorage.getItem("ih_token")).toBe("tok123");
    expect(localStorage.getItem("ih_role")).toBe("editor");
  });

  it("shows a plain error message", async () => {
    api.login.mockRejectedValue({ response: { data: { detail: "invalid email or password" } } });
    render(<Login onAuthed={vi.fn()} />);

    await fillAndSubmit("a@b.com", "wrong-password-x");
    expect(await screen.findByText(/invalid email or password/i)).toBeInTheDocument();
  });

  /**
   * The regression that matters. FastAPI answers a schema failure with a LIST
   * of error objects; rendering that into JSX throws "Objects are not valid as
   * a React child" and the whole page went white — on the first screen a new
   * user ever sees.
   */
  it("survives a 422 whose detail is an array of objects", async () => {
    api.signup.mockRejectedValue({
      response: {
        data: {
          detail: [{
            type: "value_error",
            loc: ["body", "email"],
            msg: "value is not a valid email address",
            input: "nope@insighthub.test",
          }],
        },
      },
    });
    render(<Login onAuthed={vi.fn()} />);

    await userEvent.click(screen.getByRole("button", { name: "Sign up" }));
    await fillAndSubmit("nope@insighthub.test", "correct-horse-battery");

    expect(await screen.findByText(/not a valid email address/i)).toBeInTheDocument();
    // the form is still standing, which is the actual bug being guarded
    expect(submitButton()).toHaveTextContent("Create workspace");
  });

  it("does not authenticate when signup fails", async () => {
    api.signup.mockRejectedValue({ response: { data: { detail: "email already registered" } } });
    const onAuthed = vi.fn();
    render(<Login onAuthed={onAuthed} />);

    await userEvent.click(screen.getByRole("button", { name: "Sign up" }));
    await fillAndSubmit("taken@b.com", "correct-horse-battery");

    await screen.findByText(/already registered/i);
    expect(onAuthed).not.toHaveBeenCalled();
    expect(localStorage.getItem("ih_token")).toBeNull();
  });

  it("asks for a workspace name only when signing up", async () => {
    render(<Login onAuthed={vi.fn()} />);
    expect(screen.queryByLabelText(/workspace/i)).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Sign up" }));
    expect(screen.getByLabelText(/workspace/i)).toBeInTheDocument();
  });

  it("states the password requirement up front rather than after a rejection", async () => {
    render(<Login onAuthed={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: "Sign up" }));

    expect(screen.getByLabelText(/password/i)).toHaveAttribute("minLength", "10");
    expect(screen.getByText(/avoid common passwords/i)).toBeInTheDocument();
  });

  it("defaults the role to admin when the server omits it", async () => {
    api.login.mockResolvedValue({ access_token: "tok" });
    const onAuthed = vi.fn();
    render(<Login onAuthed={onAuthed} />);

    await fillAndSubmit("a@b.com", "correct-horse-battery");
    await waitFor(() => expect(onAuthed).toHaveBeenCalledWith("admin"));
  });
});
