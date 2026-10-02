#include<iostream>
using namespace std;

int main() {
    ios_base::sync_with_stdio(false);
    cin.tie(NULL);
    int n; cin >> n;
    int curmx = 10;
    while(n--) {
        string cur; cin >> cur;
        if(cur == "/") {
            cout << curmx << '\n';
        } else {
            int x = stoi(cur);
            cout << x << '\n';
            curmx = max(curmx, x + 10 - (x % 10));
        }
    }
}
