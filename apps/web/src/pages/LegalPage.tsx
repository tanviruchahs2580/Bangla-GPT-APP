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
      "নিবন্ধনের সময় নাম, ইমেইল, ভূমিকা ও (শিক্ষার্থীদের জন্য) শ্রেণি। ব্যবহারের সময় কুইজের উত্তর, স্কোর ও অগ্রগতির পরিসংখ্যান। টিউটরের প্রশ্নগুলো পাঠ্যবই-ভিত্তিক উত্তর দিতে ব্যবহৃত হয়।",
    bodyEn:
      "At registration: name, email, role and (for students) class level. During use: quiz answers, scores and progress statistics. Tutor questions are used to provide textbook-grounded answers.",
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
      "পাসওয়ার্ড PBKDF2 দিয়ে হ্যাশ করা হয়, সেশন JWT টোকেন দিয়ে চলে, এবং রিসেট টোকেন শুধু হ্যাশ আকারে সংরক্ষিত হয়।",
    bodyEn:
      "Passwords are hashed with PBKDF2, sessions use JWT tokens, and password-reset tokens are stored only as hashes.",
  },
];

export default function LegalPage({ kind }: { kind: "privacy" | "terms" }) {
  const isPrivacy = kind === "privacy";
  return (
    <div className="card" style={{ maxWidth: 780, margin: "40px auto" }}>
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
        <a href="/login">লগইন</a> · <a href="/register">নিবন্ধন</a>
      </p>
    </div>
  );
}
