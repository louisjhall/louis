/**
 * Coach · Exercise Demand Queue
 *
 * Iter 140f · Phase A — this standalone screen has been absorbed into the
 * Exercise Library UI. All draft/review requests now surface in the
 * "NEEDS REVIEW" tab of `/coach/exercise-content`. This route is retained
 * as a thin redirect so existing links / bookmarks continue to work.
 *
 * No collections, endpoints or data have changed. The old body of this
 * screen (approve / reject / merge / generate media modals) lives on
 * unchanged in `feature_v2_resolver.py` and is reused from the Exercise
 * Library card actions.
 */
import { useEffect } from "react";
import { View, ActivityIndicator, StyleSheet } from "react-native";
import { useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { theme } from "@/src/lib/theme";

export default function DemandQueueRedirect() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/coach/exercise-content?tab=needs_review");
  }, [router]);
  return (
    <SafeAreaView style={styles.root}>
      <View style={styles.center}>
        <ActivityIndicator color={theme.color.brand} />
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.bg },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
});
