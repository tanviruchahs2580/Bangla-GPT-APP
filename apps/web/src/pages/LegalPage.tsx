import { t } from "../i18n";

const SECTIONS: {
  titleBn: string;
  titleEn: string;
  bodyBn: string;
  bodyEn: string;
}[] = [
  {
    titleBn: "কী তথ্য সংগ্রহ করা হয়",
    titleEn: "What data we collect",
    bodyBn:
      "নিবন্ধনের সময় নাম, ইমেইল, ভূমিকা ও (শিক্ষার্থীদের জন্য) শ্রেণি। অভিভাবকের অ্যাকাউন্ট যুক্ত করলে অভিভাবকের ফোন নম্বর সংরক্ষিত হয় — এটি ঐচ্ছিক এবং শুধু অভিভাবক-শিক্ষার্থী সংযোগের জন্য ব্যবহৃত হয়। ব্যবহারের সময় কুইজের উত্তর, স্কোর ও অগ্রগতির পরিসংখ্যান। টিউটরের প্রশ্নগুলো পাঠ্যবই-ভিত্তিক উত্তর দিতে ব্যবহৃত হয়।",
    bodyEn:
      "At registration: name, email, role and (for students) class level. When a parent links an account, the guardian phone number is stored — optional, and used only for the parent–student link. During use: quiz answers, scores and progress statistics. Tutor questions are used to provide textbook-grounded answers.",
  },
  {
    titleBn: "শিশুর তথ্য ও অভিভাবকের সম্মতি",
    titleEn: "Children’s data & parental consent",
    bodyBn:
      "শিক্ষার্থী হিসেবে নিবন্ধনের জন্য অভিভাবকের সম্মতি (guardian consent) বাধ্যতামূলক। আমরা বিজ্ঞাপনদাতার কাছে কোনো তথ্য বিক্রি করি না এবং শিশুদের ডেটা টার্গেটেড বিজ্ঞাপনের জন্য ব্যবহার করি না।",
    bodyEn:
      "Guardian consent is mandatory for student accounts. We never sell data to advertisers and do not use children’s data for targeted advertising.",
  },
  {
    titleBn: "কোন তৃতীয় পক্ষ ডেটা প্রক্রিয়া করে",
    titleEn: "Who processes your data",
    bodyBn:
      "টিউটরের উত্তর তৈরি করতে আপনার প্রশ্ন (ফোন/ইমেইল/পরিচয় নম্বর মুছে ফেলার পর), পাঠ্যবইয়ের প্রাসঙ্গিক অংশ ও কথোপকথনের ইতিহাস Google-এর জেমিনি মডেল API-তে পাঠানো হয়; এটি আমাদের নির্দেশে ও চুক্তির অধীনে ডেটা প্রক্রিয়া করে। যে বিল্ডে ত্রুটি-মনিটরিং সক্রিয় থাকে, সেখানে কারিগরি ত্রুটির তথ্য Sentry-তে পাঠানো হয়।",
    bodyEn:
      "To produce tutor answers, your question (after phone, email and ID-number spans are redacted), the relevant textbook passages and the conversation history are sent to Google’s Gemini model API, which processes them on our instructions and under contract. Builds with error monitoring enabled send technical error events to Sentry.",
  },
  {
    titleBn: "কত দিন তথ্য রাখা হয়",
    titleEn: "How long we keep data",
    bodyBn:
      "চ্যাট ইতিহাস সর্বোচ্চ ১৮০ দিন রাখা হয়, এরপর স্বয়ংক্রিয়ভাবে মুছে ফেলা হয়। অ্যাকাউন্ট মুছে ফেললে তার সঙ্গে যুক্ত সব তথ্য স্থায়ীভাবে অপসারিত হয়।",
    bodyEn:
      "Chat history is kept for up to 180 days and then removed by an automatic retention sweep. Deleting your account permanently removes the data associated with it.",
  },
  {
    titleBn: "আপনার নিয়ন্ত্রণ",
    titleEn: "Your controls",
    bodyBn:
      'যেকোনো সময় "আমার ডেটা এক্সপোর্ট" ব্যবহার করে সম্পূর্ণ তথ্য JSON আকারে নামিয়ে নিতে পারবেন, এবং অ্যাকাউন্ট মুছে ফেলার মাধ্যমে সব তথ্য স্থায়ীভাবে অপসারণ করতে পারবেন।',
    bodyEn:
      "You can export everything we store about you as JSON at any time, and permanently delete your account together with all associated data.",
  },
  {
    titleBn: "ডেটা নিরাপত্তা",
    titleEn: "Data security",
    bodyBn:
      "পাসওয়ার্ড Argon2id দিয়ে হ্যাশ করা হয়, সেশন JWT টোকেন দিয়ে চলে, রিসেট টোকেন শুধু হ্যাশ আকারে সংরক্ষিত হয় এবং অভিভাবকের ফোন নম্বর এনক্রিপ্ট করে রাখা হয়।",
    bodyEn:
      "Passwords are hashed with Argon2id, sessions use JWT tokens, password-reset tokens are stored only as hashes, and the guardian phone number is stored encrypted.",
  },
];

export default function LegalPage({ kind }: { kind: "privacy" | "terms" }) {
  const isPrivacy = kind === "privacy";
  return (
    <main id="main-content" tabIndex={-1} className="card card-legal">
      <h2>
        {isPrivacy
          ? "গোপনীয়তা নীতি / Privacy Policy"
          : "ব্যবহারের শর্তাবলি / Terms of Service"}
      </h2>
      {isPrivacy ? (
        <>
          {SECTIONS.map((section) => (
            <section key={section.titleEn}>
              <h3>
                {section.titleBn} · {section.titleEn}
              </h3>
              <p>{section.bodyBn}</p>
              <p className="muted">{section.bodyEn}</p>
            </section>
          ))}
          <p className="muted">সংশোধনী তারিখ: ২০২৬-০৮-২৬</p>
        </>
      ) : (
        <>
          <section>
            <h3>১. সেবার ধরন</h3>
            <p>
              এটি একটি NCTB পাঠ্যবই-ভিত্তিক শিক্ষা সহায়ক। উত্তরগুলো সরবরাহকৃত
              পাঠ্যবইয়ের অংশ থেকে দেওয়া হয়; পরীক্ষার একমাত্র উৎস হিসেবে এটিকে
              ভরসা করবেন না।
            </p>
            <p className="muted">
              This is an NCTB-textbook-grounded study aid. Answers come from
              supplied textbook passages; do not rely on it as the sole source
              of truth.
            </p>
          </section>
          <section>
            <h3>২. অ্যাকাউন্ট দায়িত্ব</h3>
            <p>
              পাসওয়ার্ড গোপন রাখা ব্যবহারকারীর দায়িত্ব। অন্যের অ্যাকাউন্টে
              অনুপ্রবেশ বা সেবার অপব্যবহার নিষিদ্ধ।
            </p>
            <p className="muted">
              Keep your password confidential. Impersonation or abuse of the
              service is prohibited.
            </p>
          </section>
          <section>
            <h3>৩. বৌদ্ধিক সম্পত্তি</h3>
            <p>
              পাঠ্যবইয়ের বিষয়বস্তুর স্বত্ব NCTB/সংশ্লিষ্ট মালিকদের; শেখার
              উদ্দেশ্যেই ব্যবহৃত হয়।
            </p>
            <p className="muted">
              Textbook content remains the property of NCTB/rights holders and
              is used for study purposes only.
            </p>
          </section>
          <p className="muted">সংশোধনী তারিখ: ২০২৬-০৮-২৬</p>
        </>
      )}
      <p className="muted">
        <a href="/login">{t("login")}</a> ·{" "}
        <a href="/register">{t("register")}</a>
      </p>
    </main>
  );
}
