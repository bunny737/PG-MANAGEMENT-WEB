import { getTranslations } from "next-intl/server";
import { PhoneFrame } from "./PhoneFrame";

// Real screenshots of the Android app, in display order. Files live in public/app-screens/.
const SCREENS = [
  { key: "dashboard", src: "/app-screens/app-dashboard.png" },
  { key: "residents", src: "/app-screens/app-residents.png" },
  { key: "billing", src: "/app-screens/app-billing.png" },
  { key: "property", src: "/app-screens/app-property.png" },
] as const;

export async function AppScreens() {
  const t = await getTranslations("marketing.app");
  return (
    <div className="mt-10 grid grid-cols-1 gap-8 sm:grid-cols-2 lg:grid-cols-4">
      {SCREENS.map(({ key, src }) => (
        <PhoneFrame
          key={key}
          src={src}
          role={t(`screens.${key}.role`)}
          title={t(`screens.${key}.title`)}
          alt={t(`screens.${key}.alt`)}
        />
      ))}
    </div>
  );
}
