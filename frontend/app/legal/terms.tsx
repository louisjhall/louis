import React from "react";
import { View, Text, ScrollView, StyleSheet, Linking, Pressable } from "react-native";
import { Stack } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { theme } from "../../src/lib/theme";

const Section = ({ title, children }: { title: string; children: React.ReactNode }) => (
  <View style={styles.sect}>
    <Text style={styles.h2}>{title}</Text>
    {children}
  </View>
);
const P = ({ children }: { children: React.ReactNode }) => <Text style={styles.p}>{children}</Text>;
const LI = ({ children }: { children: React.ReactNode }) => <Text style={styles.li}>{"\u2022 "}{children}</Text>;

export default function Terms() {
  return (
    <SafeAreaView style={styles.wrap} edges={["top", "left", "right"]}>
      <Stack.Screen options={{ title: "Terms of Service" }} />
      <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: 60 }}>
        <Text style={styles.h1}>Terms of Service</Text>
        <Text style={styles.updated}>Last updated: June 2026</Text>

        <Section title="1. Agreement">
          <P>By creating a CrewFit account you agree to these Terms and our Privacy Policy. If you do not agree, do not use the service.</P>
        </Section>

        <Section title="2. Not medical advice">
          <P>CrewFit provides general fitness and wellbeing information. It is NOT medical, nutritional, mental-health or diagnostic advice. Consult a licensed professional before starting any programme, especially if you have injuries, medical conditions, are pregnant, or hold aviation medical certification requirements.</P>
        </Section>

        <Section title="3. Your account">
          <LI>You must be 16 or older to use CrewFit.</LI>
          <LI>Keep your credentials confidential; you are responsible for all activity on your account.</LI>
          <LI>Provide accurate information during signup and assessment.</LI>
        </Section>

        <Section title="4. Acceptable use">
          <LI>Do not misuse the automation features (excessive automated calls, scraping, or resale of generated output).</LI>
          <LI>Do not upload content that is illegal, defamatory, or violates others’ rights.</LI>
          <LI>Do not attempt to reverse-engineer, hack or disrupt the service.</LI>
        </Section>

        <Section title="5. Automated content">
          <P>Automated insights, meal estimates and travel guidance can be wrong. Always use your judgement. CrewFit is not liable for decisions you make based on automated output.</P>
        </Section>

        <Section title="6. Subscriptions and payment">
          <P>CrewFit is currently free. When paid features are introduced, subscription terms, pricing and renewal will be shown before purchase. Payments made through the iOS app will use Apple in-app purchase where required.</P>
        </Section>

        <Section title="7. Content ownership">
          <P>You own the content you upload. You grant CrewFit a limited licence to process it in order to provide the service (including via automated processors).</P>
        </Section>

        <Section title="8. Suspension and termination">
          <P>We may suspend accounts that violate these Terms or that misuse the service. You may delete your account at any time from within the app.</P>
        </Section>

        <Section title="9. Liability">
          <P>To the extent permitted by law, CrewFit’s total liability is limited to the amount you paid us in the previous 12 months. We are not liable for indirect or consequential losses.</P>
        </Section>

        <Section title="10. Changes">
          <P>We may update these Terms. Material changes will be notified in-app. Continued use after changes take effect means you accept the new Terms.</P>
        </Section>

        <Section title="11. Contact">
          <Pressable onPress={() => Linking.openURL("mailto:louis@crewfit.net")}>
            <Text style={styles.link}>louis@crewfit.net</Text>
          </Pressable>
        </Section>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  wrap: { flex: 1, backgroundColor: theme.color.surface },
  h1: { color: theme.color.text, fontFamily: theme.font.display, fontSize: 28, marginBottom: 4 },
  updated: { color: theme.color.textDim, fontFamily: theme.font.text, fontSize: 12, marginBottom: 20 },
  sect: { marginBottom: 20 },
  h2: { color: theme.color.text, fontFamily: theme.font.textBold, fontSize: 17, marginBottom: 8 },
  p: { color: theme.color.textMuted, fontFamily: theme.font.text, fontSize: 14, lineHeight: 22, marginBottom: 6 },
  li: { color: theme.color.textMuted, fontFamily: theme.font.text, fontSize: 14, lineHeight: 22, marginBottom: 4 },
  link: { color: theme.color.brand, fontFamily: theme.font.textSemi, fontSize: 15 },
});
