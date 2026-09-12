import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { SearchBox } from "../components/SearchBox";
import { t } from "../i18n";
import type { SearchResponse } from "../types";

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  postStream: vi.fn(),
  patch: vi.fn(),
  del: vi.fn(),
}));

vi.mock("../api", () => apiMock);

const RESULT: SearchResponse = {
  query: "kos",
  ask_action: true,
  hits: [
    {
      kind: "question",
      title: "Kosh ki",
      subtitle: "Kosh - Biggan",
      href: "/student/learn/science/Kosh?class=6",
      score: 5.2,
    },
    {
      kind: "chapter",
      title: "Jibkosh o Tishu",
      subtitle: "Biggan",
      href: "/student/learn/science/Jibkosh?class=10",
      score: 4.1,
    },
  ],
};

function LocationProbe() {
  const loc = useLocation();
  return (
    <div data-testid="probe">
      {loc.pathname + loc.search + "|" + JSON.stringify(loc.state)}
    </div>
  );
}

function renderBox() {
  return render(
    <MemoryRouter initialEntries={["/student"]}>
      <SearchBox />
      <LocationProbe />
    </MemoryRouter>,
  );
}

describe("S1.11 global search dropdown", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("queries /search after debounce and shows question + chapter results", async () => {
    apiMock.get.mockResolvedValue(structuredClone(RESULT));
    const user = userEvent.setup();
    renderBox();

    await user.type(screen.getByLabelText(t("searchPlaceholder")), "kos");

    await waitFor(
      () => expect(apiMock.get).toHaveBeenCalledWith("/search?q=kos"),
      {
        timeout: 2000,
      },
    );
    expect(await screen.findByText("Kosh ki")).toBeInTheDocument();
    expect(screen.getByText("Jibkosh o Tishu")).toBeInTheDocument();
    // the ask-in-tutor action appears for question-like queries
    expect(screen.getByText(t("searchAskTutor"))).toBeInTheDocument();
  });

  it("navigates to the chapter route when a result is clicked", async () => {
    apiMock.get.mockResolvedValue(structuredClone(RESULT));
    const user = userEvent.setup();
    renderBox();

    await user.type(screen.getByLabelText(t("searchPlaceholder")), "kos");
    await user.click(await screen.findByText("Jibkosh o Tishu"));

    await waitFor(() =>
      expect(screen.getByTestId("probe")).toHaveTextContent(
        "/student/learn/science/Jibkosh?class=10|null",
      ),
    );
  });

  it("the ask action navigates to the tutor with the query in state", async () => {
    apiMock.get.mockResolvedValue(structuredClone(RESULT));
    const user = userEvent.setup();
    renderBox();

    await user.type(screen.getByLabelText(t("searchPlaceholder")), "kos");
    await user.click(await screen.findByText(t("searchAskTutor")));

    await waitFor(() =>
      expect(screen.getByTestId("probe")).toHaveTextContent(
        '/student/tutor|{"ask":"kos"}',
      ),
    );
  });

  it("shows the empty state when nothing matches", async () => {
    apiMock.get.mockResolvedValue({
      query: "zzz",
      ask_action: false,
      hits: [],
    });
    const user = userEvent.setup();
    renderBox();

    await user.type(screen.getByLabelText(t("searchPlaceholder")), "zzz");

    expect(await screen.findByText(t("searchNoResults"))).toBeInTheDocument();
  });
});
